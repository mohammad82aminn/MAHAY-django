from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .fields import MobileNumberField
from .managers import UserManager
from .validators import MOBILE_NUMBER_REGEX


class User(AbstractBaseUser, PermissionsMixin):
    mobile_number = MobileNumberField(
        _("شماره موبایل"),
        unique=True,
        error_messages={"unique": _("کاربری با این شماره موبایل وجود دارد.")},
    )
    first_name = models.CharField(_("نام"), max_length=150, blank=True)
    last_name = models.CharField(_("نام خانوادگی"), max_length=150, blank=True)
    email = models.EmailField(
        _("ایمیل"),
        unique=True,
        blank=True,
        null=True,  # Users without email store NULL, so they don't collide on unique
        error_messages={"unique": _("کاربری با این ایمیل وجود دارد.")},
    )
    is_active = models.BooleanField(_("فعال"), default=True)
    is_staff = models.BooleanField(_("دسترسی پنل مدیریت"), default=False)
    date_joined = models.DateTimeField(_("تاریخ عضویت"), default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "mobile_number"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _("کاربر")
        verbose_name_plural = _("کاربران")
        constraints = [
            # Last line of defense: DB rejects any non-canonical mobile number
            models.CheckConstraint(
                condition=models.Q(mobile_number__regex=MOBILE_NUMBER_REGEX),
                name="accounts_user_mobile_number_format",
                violation_error_message=_("فرمت شماره موبایل نامعتبر است."),
            ),
        ]

    def __str__(self):
        return self.get_full_name() or self.email or self.mobile_number

    def clean(self):
        super().clean()
        self.email = self.normalize_email_value(self.email)

    def save(self, *args, **kwargs):
        self.email = self.normalize_email_value(self.email)
        super().save(*args, **kwargs)

    @staticmethod
    def normalize_email_value(email):
        # "" -> None (avoid unique collision); lowercase for case-insensitive uniqueness
        email = (email or "").strip().lower()
        return email or None

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name