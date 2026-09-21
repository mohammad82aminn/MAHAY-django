from django.db.models import Exists, OuterRef, Q
from django.utils.functional import SimpleLazyObject

from domains.models import Domain

from .models import Product


def _holds(product_type):
    """Whether the domain being annotated has a product of this type to show."""
    products = Product.objects.visible().filter(product_type=product_type)
    return Exists(products.filter(Q(primary_domain=OuterRef("pk")) | Q(related_domains=OuterRef("pk"))))


def _nav_domains():
    """
    Active domains, each carrying whether it has anything to offer under each section.

    The menus only list a domain that actually holds something, so nobody is sent to an empty
    page. Both answers come from one query, and the flags match what the list page would show:
    a product counts for its own domain and for the domains it is shown in.
    """
    return list(
        Domain.objects.filter(is_active=True)
        .annotate(has_course=_holds(Product.Type.COURSE), has_project=_holds(Product.Type.PROJECT))
        .only("name", "slug")
    )


def store_nav(request):
    # Lazy on purpose: the query only runs for a page whose template opens the menus
    return {"nav_domains": SimpleLazyObject(_nav_domains)}
