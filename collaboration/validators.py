"""
Limits on the files somebody attaches to an application.

Note that nginx must also carry a client_max_body_size of the same order: Django writes the
whole upload to a temporary file before any validator here gets to look at it.
"""
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.utils.translation import gettext_lazy as _

MAX_FILE_MB = 10
MAX_FILES = 5

ALLOWED_EXTENSIONS = ["pdf", "doc", "docx", "txt", "png", "jpg", "jpeg", "zip", "rar", "7z"]

validate_file_extension = FileExtensionValidator(
    ALLOWED_EXTENSIONS,
    message=_("این نوع فایل پذیرفته نمی‌شود. رزومه را به صورت PDF یا Word بفرستید."),
)


def validate_file_size(file):
    if file.size > MAX_FILE_MB * 1024 * 1024:
        raise ValidationError(
            _("حجم هر فایل نباید بیشتر از %(limit)d مگابایت باشد."),
            params={"limit": MAX_FILE_MB},
        )
