"""
The pages a visitor sees when something goes wrong (used only while DEBUG is off).

They are rendered without the request, so none of the context processors run: an error page costs
no database query (bots asking for addresses that don't exist are most of the 404s), and it still
works when the database itself is the thing that failed. Nothing about the request or the error is
shown; the details go to the log (see LOGGING in settings).
"""
from django.http import HttpResponse
from django.template.loader import render_to_string


def _page(template_name, status):
    return HttpResponse(render_to_string(template_name), status=status)


def bad_request(request, exception):
    return _page("400.html", 400)


def permission_denied(request, exception):
    return _page("403.html", 403)


def page_not_found(request, exception):
    return _page("404.html", 404)


def server_error(request):
    return _page("500.html", 500)
