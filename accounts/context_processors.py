from . import pending


def pending_work(request):
    """
    The number beside the «پنل مدیریت» link in the site header.

    Like the کارپوشه badge, this returns nothing at all for visitors and customers so that the
    public pages carry no extra query; only somebody who can act on the work pays for counting it.
    """
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_staff", False):
        return {}
    return {"pending_total": pending.total(request)}
