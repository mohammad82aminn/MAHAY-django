from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from products.models import Product
from content import progress
from . import gateway, services
from .models import CartItem, Order, Purchase

ADD_MESSAGES = {
    "added": (messages.SUCCESS, "به سبد خرید اضافه شد."),
    "already_in_cart": (messages.INFO, "این محصول از قبل در سبد خرید شما است."),
    "already_owned": (messages.INFO, "شما این محصول را دارید؛ از «خریدهای من» ببینید."),
    "unavailable": (messages.ERROR, "این محصول در حال حاضر قابل خرید نیست."),
}


@require_POST
def add_to_cart(request, slug):
    product = get_object_or_404(Product, slug=slug)
    level, text = ADD_MESSAGES[services.add_to_cart(request, product)]
    messages.add_message(request, level, text)
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
        messages.info(request, "از سبد خرید حذف شد.")
    return redirect("commerce:cart")


def cart_view(request):
    cart = services.get_cart(request)
    products = list(cart.products.select_related("primary_domain")) if cart else []
    return render(request, "commerce/cart.html", {
        "products": products,
        "total": sum(product.final_price for product in products),
        "owned_ids": services.owned_product_ids(request.user),
    })


@login_required
@require_POST
def checkout(request):
    """Login is only required here: browsing and filling the cart work without an account."""
    cart = services.get_cart(request)
    order = services.create_order(request.user, cart) if cart else None
    if order is None:
        messages.error(request, "سبد خرید شما خالی است.")
        return redirect("commerce:cart")

    if order.is_free:  # ZarinPal can't process a zero payment
        order.mark_paid(message="سفارش رایگان")
        services.clear_paid_items(cart, order)
        messages.success(request, "محصولات رایگان به حساب شما اضافه شد.")
        return redirect("commerce:order_detail", number=order.number)

    callback_url = request.build_absolute_uri(reverse("commerce:payment_callback"))
    try:
        order.authority, payment_url = gateway.request_payment(order, callback_url)
    except gateway.PaymentError as error:
        order.status = Order.Status.FAILED
        order.gateway_message = str(error)[:255]
        order.save()
        messages.error(request, str(error))
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
        messages.error(request, "سفارش این پرداخت پیدا نشد.")
        return redirect("home")

    if order.status == Order.Status.PAID:  # e.g. the user refreshed the callback page
        return redirect("commerce:order_detail", number=order.number)

    if request.GET.get("Status") != "OK":
        order.status = Order.Status.CANCELED
        order.gateway_message = "پرداخت توسط کاربر لغو شد."
        order.save()
        messages.warning(request, "پرداخت لغو شد. سبد خرید شما محفوظ است.")
        return redirect("commerce:cart")

    try:
        data = gateway.verify_payment(order)
    except gateway.PaymentError as error:
        order.status = Order.Status.FAILED
        order.gateway_message = str(error)[:255]
        order.save()
        messages.error(request, f"پرداخت تأیید نشد: {error}")
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

    messages.success(request, "پرداخت با موفقیت انجام شد.")
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