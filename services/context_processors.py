from .models import ContactChannel


def contact_channels(request):
    """Our contact IDs, for the footer and the contact page."""
    return {"contact_channels": ContactChannel.objects.filter(is_active=True)}