from . import services


def cart(request):
    """Number of items in the cart, for the icon in the header."""
    if request.path.startswith("/admin/"):
        return {}  # the panel has no cart icon; skip its query on every panel page
    cart = services.get_cart(request)
    return {"cart_count": cart.count if cart else 0}