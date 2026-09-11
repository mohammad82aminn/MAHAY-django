from urllib.parse import urlparse

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

APARAT_HOSTS = ("aparat.com", "www.aparat.com")


def validate_aparat_url(value):
    if value and urlparse(value).hostname not in APARAT_HOSTS:
        raise ValidationError(_("فقط لینک آپارات پذیرفته می‌شود."))