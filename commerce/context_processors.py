from . import services


def cart(request):
    """Number of items in the cart, for the icon in the header."""
    cart = services.get_cart(request)
    return {"cart_count": cart.count if cart else 0}