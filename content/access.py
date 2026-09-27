"""
Who may open protected files (videos, attachments, thesis) of a product:
- the buyer (a Purchase row exists — it stays valid even if the product leaves the store)
- the people of the product's domain (its managers and experts), and site admins (to check the content)
"""
from accounts.roles import is_site_admin
from domains.access import is_member


def can_manage(user, product):
    return is_site_admin(user) or is_member(user, product.primary_domain)


def owns(user, product):
    from commerce.models import Purchase

    return Purchase.objects.filter(user=user, product=product).exists()


def can_open(user, product):
    if not user.is_authenticated:
        return False
    return owns(user, product) or can_manage(user, product)