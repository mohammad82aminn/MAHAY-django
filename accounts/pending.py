"""
How much work is waiting for the person looking at the panel.

Each ModelAdmin answers for itself by defining pending_count(request); nothing is registered
centrally, so an app that grows a new kind of waiting work only has to say so in its own admin.
A count is always taken from that admin's own get_queryset(), which is what keeps one manager
from learning how much traffic a section they cannot open is getting.
"""
from django.contrib import admin


def count_for(model, request):
    """
    What this model has waiting for the visitor, or 0 when it reports nothing.

    Kept on the request: one panel page asks for the same count up to three times (the total in
    the header, the section in the sidebar, the part itself), and each is a query.
    """
    cache = getattr(request, "_pending_counts", None)
    if cache is None:
        cache = {}
        try:
            request._pending_counts = cache
        except AttributeError:
            pass
    if model not in cache:
        cache[model] = _count(model, request)
    return cache[model]


def _count(model, request):
    model_admin = admin.site._registry.get(model)
    counter = getattr(model_admin, "pending_count", None)
    if counter is None or not model_admin.has_view_permission(request):
        return 0
    # The technical admins see everything to find faults, not to do the work: a new order or a
    # waiting approval isn't theirs to clear, so only a section that says so counts for them
    if is_tech_only(request.user) and not getattr(model_admin, "counts_for_tech_admins", False):
        return 0
    return counter(request)


def is_tech_only(user):
    from .roles import is_site_admin, is_tech_admin

    return is_tech_admin(user) and not is_site_admin(user)


def total(request):
    """Everything waiting, for the one number shown beside the panel link in the site header."""
    if not getattr(request.user, "is_staff", False):
        return 0
    return sum(count_for(model, request) for model in admin.site._registry)
