"""
How much work is waiting for the person looking at the panel.

Each ModelAdmin answers for itself by defining pending_count(request); nothing is registered
centrally, so an app that grows a new kind of waiting work only has to say so in its own admin.
A count is always taken from that admin's own get_queryset(), which is what keeps one manager
from learning how much traffic a section they cannot open is getting.
"""
from django.contrib import admin


def count_for(model, request):
    """What this model has waiting for the visitor, or 0 when it reports nothing."""
    model_admin = admin.site._registry.get(model)
    counter = getattr(model_admin, "pending_count", None)
    if counter is None or not model_admin.has_view_permission(request):
        return 0
    return counter(request)


def total(request):
    """Everything waiting, for the one number shown beside the panel link in the site header."""
    if not getattr(request.user, "is_staff", False):
        return 0
    return sum(count_for(model, request) for model in admin.site._registry)
