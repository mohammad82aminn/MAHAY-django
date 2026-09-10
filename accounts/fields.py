from django.core.exceptions import ValidationError
from django.core.validators import EMPTY_VALUES
from django.db import models

from .validators import normalize_mobile_number


class MobileNumberField(models.CharField):
    """
    Stores Iranian mobile numbers in one canonical format (+989xxxxxxxxx).

    - Forms, Admin and createsuperuser: input is normalized and validated (to_python).
    - Queries / login: lookup values are normalized, so "0912..." finds "+98912..." (get_prep_value).
    """

    description = "Iranian mobile number (+989xxxxxxxxx)"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 13)
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        value = super().to_python(value)
        if value in EMPTY_VALUES:
            return value
        return normalize_mobile_number(value)

    def get_prep_value(self, value):
        # CharField.get_prep_value calls to_python, so lookups are normalized too.
        try:
            return super().get_prep_value(value)
        except ValidationError:
            # Invalid lookup value: keep it as-is so the query simply finds nothing
            # (login with garbage input must return "user not found", not crash).
            return value

    def formfield(self, **kwargs):
        # Raw input like "0098 912 123 4567" is longer than the stored 13 chars.
        return super().formfield(**{"max_length": 20, **kwargs})