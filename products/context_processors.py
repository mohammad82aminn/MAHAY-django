from domains.models import Domain


def store_nav(request):
    """Active domains for the header menu (lazy: only queried when a template uses it)."""
    return {"nav_domains": Domain.objects.filter(is_active=True).only("name", "slug")}