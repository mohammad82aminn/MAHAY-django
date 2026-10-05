from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html_join
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.utils.translation import gettext_noop
from django.views.decorators.http import require_POST

from pages.models import Page
from products.models import Product
from content import progress
from . import gateway, services
from .models import CartItem, Order, Purchase

ADD_MESSAGES = {
    "added": (messages.SUCCESS, gettext_lazy("به سبد خرید اضافه شد.")),
    "already_in_cart": (messages.INFO, gettext_lazy("این محصول از قبل در سبد خرید شما است.")),
    "already_owned": (messages.INFO, gettext_lazy("شما این محصول را دارید؛ از «خریدهای من» ببینید.")),
    "unavailable": (messages.ERROR, gettext_lazy("این محصول در حال حاضر قابل خرید نیست.")),
}

# Kept on the order (gateway_message) in Persian, the site's own language, and translated where it
# is shown (order_detail.html), so a buyer reads it in the language of the page they are on.
CANCELED_BY_BUYER = gettext_noop("پرداخت توسط کاربر لغو شد.")
FREE_ORDER = gettext_noop("سفارش رایگان")

# The pages a buyer agrees to before paying (edited in the admin, under «صفحه‌ها»)
TERMS_PAGES = ("terms", "refund")


def purchase_terms():
    """
    The published pages among TERMS_PAGES. Agreeing is asked for only while there is something to
    read: a box pointing at a page that has been taken down would be a promise about nothing.
    """
    return list(Page.objects.filter(slug__in=TERMS_PAGES, is_published=True))


def terms_links(pages):
    """«Terms» and «Refunds», each a link opening in a new tab, for the sentence the buyer agrees to."""
    return format_html_join(
        _(" و "), '«<a href="{}" target="_blank" rel="noopener">{}</a>»',
        ((page.get_absolute_url(), page.title) for page in pages),
    )


@require_POST
def add_to_cart(request, slug):
    product = get_object_or_404(Product, slug=slug)
    level, text = ADD_MESSAGES[services.add_to_cart(request, product)]
    messages.add_message(request, level, str(text))
    # Only back to a page of this site: «next» comes from the form, so it can be made to point anywhere
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect("commerce:cart")


@require_POST
def remove_from_cart(request, slug):
    cart = services.get_cart(request)
    if cart is not None:
        CartItem.objects.filter(cart=cart, product__slug=slug).delete()
        messages.info(request, _("از سبد خرید حذف شد."))
    return redirect("commerce:cart")


def cart_view(request):
    cart = services.get_cart(request)
    products = list(cart.products.select_related("primary_domain")) if cart else []
    return render(request, "commerce/cart.html", {
        "products": products,
        "total": sum(product.final_price for product in products),
        "owned_ids": services.owned_product_ids(request.user),
        # A visitor sees no box: they log in first, and come back to this page to tick it
        "terms_links": terms_links(purchase_terms()) if products and request.user.is_authenticated else "",
    })


@require_POST
def checkout(request):
    """Login is only required here: browsing and filling the cart work without an account."""
    if not request.user.is_authenticated:
        # Back to the cart after logging in, not to this address: the login page returns with a
        # GET, which this POST-only view would refuse with a blank error page
        return redirect_to_login(reverse("commerce:cart"))

    if request.POST.get("accept_terms") != "on" and purchase_terms():
        messages.error(request, _("برای ثبت سفارش، قوانین را بخوانید و تیک پذیرش آن را بزنید."))
        return redirect("commerce:cart")

    cart = services.get_cart(request)
    order = services.create_order(request.user, cart) if cart else None
    if order is None:
        messages.error(request, _("سبد خرید شما خالی است."))
        return redirect("commerce:cart")

    if order.is_free:  # ZarinPal can't process a zero payment
        order.mark_paid(message=FREE_ORDER)
        services.clear_paid_items(cart, order)
        messages.success(request, _("محصولات رایگان به حساب شما اضافه شد."))
        return redirect("commerce:order_detail", number=order.number)

    callback_url = request.build_absolute_uri(reverse("commerce:payment_callback"))
    try:
        order.authority, payment_url = gateway.request_payment(order, callback_url)
    except gateway.PaymentError as error:
        order.status = Order.Status.FAILED
        order.gateway_message = str(error)[:255]
        order.save()
        messages.error(request, _(str(error)))
        return redirect("commerce:cart")

    order.save()
    return redirect(payment_url)


def payment_callback(request):
    """
    ZarinPal sends the user back here. The money is only confirmed after verify,
    so we never trust the Status parameter alone.
    """
    order = Order.objects.filter(authority=request.GET.get("Authority", "")).first()
    if order is None:
        messages.error(request, _("سفارش این پرداخت پیدا نشد."))
        return redirect("home")

    if order.status == Order.Status.PAID:  # e.g. the user refreshed the callback page
        return redirect("commerce:order_detail", number=order.number)

    if request.GET.get("Status") != "OK":
        order.status = Order.Status.CANCELED
        order.gateway_message = CANCELED_BY_BUYER
        order.save()
        messages.warning(request, _("پرداخت لغو شد. سبد خرید شما محفوظ است."))
        return redirect("commerce:cart")

    try:
        data = gateway.verify_payment(order)
    except gateway.PaymentError as error:
        order.status = Order.Status.FAILED
        order.gateway_message = str(error)[:255]
        order.save()
        messages.error(request, _("پرداخت تأیید نشد: %(error)s") % {"error": _(str(error))})
        return redirect("commerce:cart")

    with transaction.atomic():
        order.mark_paid(
            reference_id=str(data.get("ref_id", "")),
            card_pan=str(data.get("card_pan", "")),
            message=str(data.get("message", ""))[:255],
        )
        cart = services.get_cart(request)
        if cart is not None:
            services.clear_paid_items(cart, order)

    messages.success(request, _("پرداخت با موفقیت انجام شد."))
    return redirect("commerce:order_detail", number=order.number)


@login_required
def order_detail(request, number):
    order = get_object_or_404(Order.objects.prefetch_related("items__product"), number=number, user=request.user)
    return render(request, "commerce/order_detail.html", {"order": order})


@login_required
def order_list(request):
    orders = Order.objects.filter(user=request.user).prefetch_related("items")
    return render(request, "commerce/order_list.html", {"orders": orders})


@login_required
def library(request):
    """"My purchases": everything the user owns, with how far they got in each one."""
    purchases = Purchase.objects.filter(user=request.user).select_related("product__primary_domain")
    items = [
        {"product": purchase.product, **progress.summary(request.user, purchase.product)}
        for purchase in purchases
    ]
    return render(request, "commerce/library.html", {"purchases": items})