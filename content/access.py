"""
Who may open protected files (videos, attachments) of a product.

Now: site admins and the managers of the product's domain (to check content).
Commerce stage: + users who own the product (bought it, or a product that includes it).
"""
from accounts.roles import is_site_admin


def can_manage(user, product):
    return is_site_admin(user) or product.primary_domain.group.user_set.filter(pk=user.pk).exists()


def can_open(user, product):
    if not user.is_authenticated:
        return False
    return can_manage(user, product)