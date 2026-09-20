"""
Limits on what may be attached to an internal message.

Kept here rather than shared with services.validators so the two can move apart: what a guest
may send us and what colleagues may send each other are different questions.
Note that nginx must also carry a client_max_body_size of the same order: Django writes the
whole upload to a temporary file before any validator here gets to look at it.
"""
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.utils.translation import gettext_lazy as _

MAX_FILE_MB = 10

ALLOWED_EXTENSIONS = [
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt",
    "zip", "rar", "7z",
    "png", "jpg", "jpeg", "webp",
]

validate_file_extension = FileExtensionValidator(
    ALLOWED_EXTENSIONS,
    message=_("این نوع فایل پذیرفته نمی‌شود. سند، تصویر یا فایل فشرده بفرستید."),
)


def validate_file_size(file):
    if file.size > MAX_FILE_MB * 1024 * 1024:
        raise ValidationError(
            _("حجم فایل نباید بیشتر از %(limit)d مگابایت باشد."),
            params={"limit": MAX_FILE_MB},
        )
