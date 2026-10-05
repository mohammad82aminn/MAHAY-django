from typing import ClassVar
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .fields import MobileNumberField
from .managers import UserManager
from .validators import MOBILE_NUMBER_REGEX


class VerificationCode(models.Model):
    """A one-time code sent by SMS. Only its hash is stored."""

    class Purpose(models.TextChoices):
        SIGNUP = "signup", _("تأیید شماره در ثبت‌نام")
        PASSWORD_RESET = "reset", _("بازیابی رمز عبور")

    mobile_number = models.CharField(_("شماره موبایل"), max_length=13, db_index=True)
    purpose = models.CharField(_("کاربرد"), max_length=10, choices=Purpose.choices)
    code_hash = models.CharField(_("کد (هش‌شده)"), max_length=128)
    attempts = models.PositiveSmallIntegerField(_("تلاش‌های ناموفق"), default=0)
    created_at = models.DateTimeField(_("زمان ارسال"), auto_now_add=True)
    expires_at = models.DateTimeField(_("زمان انقضا"))
    used_at = models.DateTimeField(_("زمان استفاده"), null=True, blank=True)

    class Meta:
        verbose_name = _("کد تأیید")
        verbose_name_plural = _("کدهای تأیید")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.Purpose(self.purpose).label} — {self.mobile_number}"


class LoginAttempt(models.Model):
    """
    A failed login. Kept so that guessing passwords becomes impossible:
    too many failures for one number (or from one IP) block new tries for a while.
    Successful logins delete the rows, so a normal user is never affected.
    """

    mobile_number = models.CharField(_("شماره موبایل"), max_length=20, db_index=True)
    ip_address = models.GenericIPAddressField(_("آی‌پی"), null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(_("زمان"), auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("تلاش ناموفق ورود")
        verbose_name_plural = _("تلاش‌های ناموفق ورود")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.mobile_number} — {self.created_at:%Y/%m/%d %H:%M}"

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
    is_active = models.BooleanField(
        _("فعال"), default=True,
        help_text=_("کاربر غیرفعال نمی‌تواند وارد شود. ثبت‌نام‌های تأییدنشده غیرفعال می‌مانند."),
    )
    mobile_verified = models.BooleanField(
        _("شماره تأیید شده"), default=False, help_text=_("با کد پیامکی تأیید شده است."),
    )
    
    contact_handle = models.CharField(
        _("آیدی ارتباطی"), max_length=150, blank=True,
        help_text=_("مثلاً @ali در تلگرام. برای معرفی کارشناس به مشتری استفاده می‌شود."),
    )

    is_staff = models.BooleanField(_("دسترسی پنل مدیریت"), default=False)
    date_joined = models.DateTimeField(_("تاریخ عضویت"), default=timezone.now)

       
    objects: ClassVar[UserManager] = UserManager()

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

    @property
    def is_site_admin(self):
        """Superuser or member of the site admins group."""
        from .roles import is_site_admin

        return is_site_admin(self)

    @property
    def managed_domains(self):
        """Domains this user manages (through their «مدیران حوزه» groups)."""
        from domains.access import managed_domains

        return managed_domains(self)

    @property
    def mobile_display(self):
        """Friendly local format for templates: +989121234567 -> 0912 123 4567"""
        n = f"0{self.mobile_number[3:]}"
        return f"{n[:4]} {n[4:7]} {n[7:]}"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name

class StaffDefaultGiven(models.Model):
    """
    A starting permission a staff group has already been given (see roles.ensure_site_admins_group).

    Each migrate gives the staff groups only the starting permissions they were never given: those
    of a new model, say. One a site admin took away is on this list, so it stays taken away.
    """

    group = models.ForeignKey("auth.Group", on_delete=models.CASCADE, related_name="+")
    permission = models.ForeignKey("auth.Permission", on_delete=models.CASCADE, related_name="+")

    class Meta:
        verbose_name = _("دسترسی پیش‌فرض داده‌شده")
        verbose_name_plural = _("دسترسی‌های پیش‌فرض داده‌شده")
        constraints = [models.UniqueConstraint(fields=("group", "permission"), name="staff_default_given_once")]
