"""Cart and order logic: one place for the rules, so views stay short."""
from django.db import transaction

from products.models import Product

from .models import Cart, CartItem, Order, OrderItem, Purchase


def owned_product_ids(user):
    """Products the user already owns (bought or received for free)."""
    if not user.is_authenticated:
        return set()
    return set(Purchase.objects.filter(user=user).values_list("product_id", flat=True))


SESSION_KEY = "cart_id"  # a guest's cart id lives in their session


def get_cart(request, create=False):
    """The visitor's cart: the user's own cart when logged in, otherwise the guest cart of this session."""
    if request.user.is_authenticated:
        if create:
            cart, _ = Cart.objects.get_or_create(user=request.user)
            return cart
        return Cart.objects.filter(user=request.user).first()

    cart = Cart.objects.filter(pk=request.session.get(SESSION_KEY), user=None).first()
    if cart is None and create:
        cart = Cart.objects.create()
        request.session[SESSION_KEY] = cart.pk
    return cart


@transaction.atomic
def merge_carts(request, user):
    """
    On login: move the guest cart's products into the user's cart, so nothing they picked is lost.
    (Session data survives login, so the guest cart id is still there.)
    """
    guest_cart = Cart.objects.filter(pk=request.session.pop(SESSION_KEY, None), user=None).first()
    if guest_cart is None:
        return
    user_cart, _ = Cart.objects.get_or_create(user=user)
    owned = owned_product_ids(user)
    for product in Product.objects.filter(cart_items__cart=guest_cart):
        if product.pk not in owned:
            CartItem.objects.get_or_create(cart=user_cart, product=product)
    guest_cart.delete()


def add_to_cart(request, product):
    """Returns a message key: added / already_in_cart / already_owned / unavailable."""
    if not Product.objects.visible().filter(pk=product.pk).exists():
        return "unavailable"
    if product.pk in owned_product_ids(request.user):
        return "already_owned"
    cart = get_cart(request, create=True)
    _, created = CartItem.objects.get_or_create(cart=cart, product=product)
    return "added" if created else "already_in_cart"


@transaction.atomic
def create_order(user, cart):
    """
    Turn the cart into an order, freezing today's prices.
    Products the user already owns are skipped. Returns None if nothing is left to buy.
    """
    owned = owned_product_ids(user)
    products = [product for product in cart.products if product.pk not in owned]
    if not products:
        return None

    order = Order.objects.create(user=user, total=sum(product.final_price for product in products))
    OrderItem.objects.bulk_create([
        OrderItem(order=order, product=product, title=product.title, price=product.final_price)
        for product in products
    ])
    return order


def clear_paid_items(cart, order):
    """After a successful payment, remove exactly the bought products from the cart."""
    bought = OrderItem.objects.filter(order=order).values("product")
    CartItem.objects.filter(cart=cart, product__in=bought).delete()