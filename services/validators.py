"""
Limits on what a visitor may attach to a request.

The form is open to guests, so without these anyone could fill the disk with one upload.
Note that nginx must also carry a client_max_body_size of the same order: Django writes the
whole upload to a temporary file before any validator here gets to look at it.
"""
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.utils.translation import gettext_lazy as _

MAX_ATTACHMENT_MB = 10

ALLOWED_EXTENSIONS = [
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt",
    "zip", "rar", "7z",
    "png", "jpg", "jpeg", "webp",
]

validate_attachment_extension = FileExtensionValidator(
    ALLOWED_EXTENSIONS,
    message=_("این نوع فایل پذیرفته نمی‌شود. سند، تصویر یا فایل فشرده بفرستید."),
)


def validate_attachment_size(file):
    if file.size > MAX_ATTACHMENT_MB * 1024 * 1024:
        raise ValidationError(
            _("حجم فایل نباید بیشتر از %(limit)d مگابایت باشد."),
            params={"limit": MAX_ATTACHMENT_MB},
        )
