"""Display helpers for the admin, whose pages are right-to-left."""
from django.utils.html import format_html


def ltr(value):
    """
    Keep a latin or numeric value readable on a right-to-left page.

    "+" carries no direction of its own, so on a Persian page the browser hands it the
    direction of the paragraph and draws it at the visual end: +989121234567 is read by
    a human as 989121234567+. Marking the value itself as left-to-right settles that.
    """
    return format_html('<span dir="ltr">{}</span>', value) if value else "—"
