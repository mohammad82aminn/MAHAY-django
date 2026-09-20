from . import services


def unread(request):
    """
    The number on the کارپوشه badge, for the site header and the admin.

    This runs on every rendered page, so it returns nothing at all for visitors and customers:
    only somebody who actually holds a role costs the extra COUNT.
    """
    user = getattr(request, "user", None)
    if user is None or not services.has_inbox(user):
        return {}
    return {"inbox_unread": services.unread_count(user)}
