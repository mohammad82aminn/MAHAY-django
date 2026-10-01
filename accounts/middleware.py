class RoleCacheMiddleware:
    """
    Lets an admin page ask the visitor's groups once instead of once per role check (see
    accounts.roles.group_names). Only for the panel: the public pages ask few such questions, and
    leaving them alone keeps request.user lazy there. The mark lives on this request's own user
    object, so it ends with the request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/admin/"):
            request.user._mahay_cache_groups = True
        return self.get_response(request)
