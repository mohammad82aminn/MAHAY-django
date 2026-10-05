"""The same page in the site's other language (the switch in the header, and the hreflang links for search engines)."""
from django import template
from django.conf import settings
from django.urls import translate_url
from django.utils import translation

register = template.Library()


@register.simple_tag(takes_context=True)
def page_languages(context):
    """
    [{"code", "name", "url", "is_current"}] for each language of the site: this page's own address
    in it, query string kept (/products/?type=course <-> /en/products/?type=course).
    No request (an error page) -> each language's home page.
    """
    request = context.get("request")
    current = translation.get_language()
    languages = []
    for code, name in settings.LANGUAGES:
        if request is not None:
            url = translate_url(request.get_full_path(), code)
        else:
            url = "/" if code == settings.LANGUAGE_CODE else f"/{code}/"
        languages.append({"code": code, "name": name, "url": url, "is_current": code == current})
    return languages
