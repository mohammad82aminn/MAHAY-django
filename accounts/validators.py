import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# Persian (۰-۹) and Arabic-Indic (٠-٩) digits -> ASCII digits
DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "0123456789" * 2)

# Spaces, dashes, parentheses, dots and invisible direction/joiner marks
_SEPARATORS = re.compile(r"[\s\-().\u200c\u200e\u200f]")

# Accepted prefixes before the 10-digit national number (9xxxxxxxxx)
_PREFIXES = ("+98", "0098", "98", "0")

_NATIONAL_NUMBER = re.compile(r"^9\d{9}$")

MOBILE_NUMBER_REGEX = r"^\+989\d{9}$"


def normalize_mobile_number(value):
    """
    Convert any common Iranian mobile format to +989xxxxxxxxx.
    Raises ValidationError if the value is not a valid mobile number.
    """
    number = _SEPARATORS.sub("", str(value).translate(DIGIT_MAP))

    for prefix in _PREFIXES:
        if number.startswith(prefix) and len(number) - len(prefix) == 10:
            number = number[len(prefix):]
            break

    if not _NATIONAL_NUMBER.match(number):
        raise ValidationError(
            _("شماره موبایل معتبر نیست. نمونه صحیح: 09121234567"),
            code="invalid_mobile_number",
        )

    return f"+98{number}"