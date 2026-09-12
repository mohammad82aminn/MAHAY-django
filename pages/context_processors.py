from .models import Page


def footer_pages(request):
    """Pages listed in the footer (edited in the admin panel)."""
    return {"footer_pages": Page.objects.filter(is_published=True, show_in_footer=True)}