from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .services import merge_carts


@receiver(user_logged_in)
def merge_session_cart(sender, request, user, **kwargs):
    """A visitor filled a cart, then logged in: keep what they chose."""
    merge_carts(request, user)