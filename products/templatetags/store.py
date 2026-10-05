"""Template helpers for the store: numbers, prices, lengths and Aparat videos, in the page's language."""
import re

from django import template
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

register = template.Library()

PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
APARAT_HASH = re.compile(r"aparat\.com/v/([A-Za-z0-9]+)")


def _is_english():
    return (translation.get_language() or "").startswith("en")


@register.filter
def fa_num(value):
    """Always Persian digits, whatever the page's language: 12500 -> ۱۲٬۵۰۰ (the admin panel, messages)."""
    if value is None or value == "":
        return ""
    if isinstance(value, int):
        value = f"{value:,}".replace(",", "٬")
    return str(value).translate(PERSIAN_DIGITS)


@register.filter
def num(value):
    """A number in the page's language: 12500 -> ۱۲٬۵۰۰ on a Persian page, 12,500 on an English one."""
    if not _is_english():
        return fa_num(value)
    if value is None or value == "":
        return ""
    return f"{value:,}" if isinstance(value, int) else str(value)


@register.filter
def toman(value):
    """Price text: 0 -> رایگان, 1500000 -> ۱٬۵۰۰٬۰۰۰ تومان (Free, 1,500,000 Toman in English)"""
    if not value:
        return _("رایگان")
    return _("%(amount)s تومان") % {"amount": num(int(value))}


@register.filter
def money(value):
    """An amount of money, zero included: 0 -> ۰ تومان (a price uses `toman`, where zero means free)"""
    return _("%(amount)s تومان") % {"amount": num(int(value or 0))}


@register.filter
def duration(seconds):
    """Length of a lesson or a whole course: 45 -> ۱ دقیقه, 8100 -> ۲ ساعت و ۱۵ دقیقه, none -> empty"""
    if not seconds:
        return ""
    minutes = max(1, round(int(seconds) / 60))  # a short clip still reads as a minute, never "۰ دقیقه"
    hours, minutes = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(ngettext("%(count)s ساعت", "%(count)s ساعت", hours) % {"count": num(hours)})
    if minutes:
        parts.append(ngettext("%(count)s دقیقه", "%(count)s دقیقه", minutes) % {"count": num(minutes)})
    return _(" و ").join(parts)


@register.filter
def aparat_embed(url):
    """https://www.aparat.com/v/abc123 -> the embeddable player address (or "" if not an Aparat video link)."""
    match = APARAT_HASH.search(url or "")
    if not match:
        return ""
    return f"https://www.aparat.com/video/video/embed/videohash/{match.group(1)}/vt/frame"
