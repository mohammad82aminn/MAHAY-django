"""Template helpers for the store: Persian numbers, prices, lengths and Aparat videos."""
import re

from django import template

register = template.Library()

PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
APARAT_HASH = re.compile(r"aparat\.com/v/([A-Za-z0-9]+)")


@register.filter
def fa_num(value):
    """12500 -> ۱۲٬۵۰۰"""
    if value is None or value == "":
        return ""
    if isinstance(value, int):
        value = f"{value:,}".replace(",", "٬")
    return str(value).translate(PERSIAN_DIGITS)


@register.filter
def toman(value):
    """Price text: 0 -> رایگان, 1500000 -> ۱٬۵۰۰٬۰۰۰ تومان"""
    if not value:
        return "رایگان"
    return f"{fa_num(int(value))} تومان"


@register.filter
def duration(seconds):
    """Length of a lesson or a whole course: 45 -> ۱ دقیقه, 8100 -> ۲ ساعت و ۱۵ دقیقه, none -> empty"""
    if not seconds:
        return ""
    minutes = max(1, round(int(seconds) / 60))  # a short clip still reads as a minute, never "۰ دقیقه"
    hours, minutes = divmod(minutes, 60)
    parts = [f"{fa_num(hours)} ساعت"] if hours else []
    if minutes:
        parts.append(f"{fa_num(minutes)} دقیقه")
    return " و ".join(parts)


@register.filter
def aparat_embed(url):
    """https://www.aparat.com/v/abc123 -> the embeddable player address (or "" if not an Aparat video link)."""
    match = APARAT_HASH.search(url or "")
    if not match:
        return ""
    return f"https://www.aparat.com/video/video/embed/videohash/{match.group(1)}/vt/frame"