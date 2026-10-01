"""
An amount of money typed by hand: a wide input that groups the digits as they are typed
(150,000), the unit beside it, and the amount read out in words under it (۱۵۰ هزار تومان).

The grouping is only for the eye. Whatever arrives — with commas, Persian or Arabic digits,
spaces — is reduced to plain digits here before the form field sees it, so the page works the same
with the script off and the stored value is always a plain number.
"""
from django import forms

# Persian and Arabic-Indic digits to ASCII, and the thousands separators people type
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_SEPARATORS = str.maketrans("", "", ",٬، _'")


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def plain_number(text):
    """'۱۵۰٬۰۰۰' / '150,000' / ' 150000 ' → '150000'; anything else is left for the field to reject."""
    return text.translate(_DIGITS).translate(_SEPARATORS)


def in_words(amount):
    """
    1250000 → «۱ میلیون و ۲۵۰ هزار»; the same wording admin_money.js writes while typing.

    Written here as well so the line is already in the page when it first draws: filled in by the
    script alone, it appeared a moment later and pushed every row of the list down.
    """
    rest = int(amount)
    if not rest:
        return "۰"
    parts = []
    for size, name in ((10**9, "میلیارد"), (10**6, "میلیون"), (10**3, "هزار")):
        count, rest = divmod(rest, size)
        if count:
            parts.append(f"{count} {name}".translate(_FA_DIGITS))
    if rest:
        parts.append(str(rest).translate(_FA_DIGITS))
    return " و ".join(parts)


class MoneyInput(forms.TextInput):
    template_name = "domains/money_input.html"

    class Media:
        js = ["js/admin_money.js"]

    def __init__(self, attrs=None, unit="تومان"):
        self.unit = unit
        defaults = {
            "class": "money-input",
            "inputmode": "numeric",
            "dir": "ltr",
            "autocomplete": "off",
            "data-unit": unit,
        }
        super().__init__({**defaults, **(attrs or {})})

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["unit"] = self.unit
        try:
            context["widget"]["words"] = f"{in_words(plain_number(str(value)))} {self.unit}" if value not in (None, "") else ""
        except ValueError:
            context["widget"]["words"] = ""  # a rejected entry, shown back as typed, has no reading
        return context

    def format_value(self, value):
        if value in (None, ""):
            return None
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return str(value)  # a rejected entry is shown back as it was typed

    def value_from_datadict(self, data, files, name):
        value = super().value_from_datadict(data, files, name)
        return plain_number(value) if isinstance(value, str) else value
