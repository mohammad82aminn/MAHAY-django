"""
People asking to work with MAHAY.

Applying needs an account, so the name and the mobile number are already proven and are never
asked for again. Everything the site does with the application afterwards happens off it — the
site admin reads it and carries on the conversation wherever the applicant said to.

A rejected application keeps its text but loses its files: holding on to somebody's documents
after turning them down is a liability, not an asset.
"""
import os

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from content.storage import protected_storage

from .validators import validate_file_extension, validate_file_size


class CollaborationRequest(models.Model):
    class Status(models.TextChoices):
        NEW = "new", _("جدید")
        REVIEWING = "reviewing", _("در حال بررسی")
        ACCEPTED = "accepted", _("پذیرفته شد")
        REJECTED = "rejected", _("رد شد")

    class Channel(models.TextChoices):
        TELEGRAM = "telegram", _("تلگرام")
        WHATSAPP = "whatsapp", _("واتساپ")
        EITAA = "eitaa", _("ایتا")
        RUBIKA = "rubika", _("روبیکا")
        PHONE = "phone", _("تماس تلفنی")

    class Degree(models.TextChoices):
        DIPLOMA = "diploma", _("دیپلم")
        ASSOCIATE = "associate", _("کاردانی")
        BACHELOR = "bachelor", _("کارشناسی")
        MASTER = "master", _("کارشناسی ارشد")
        PHD = "phd", _("دکتری")

    OPEN_STATUSES = (Status.NEW, Status.REVIEWING)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="collaboration_requests", verbose_name=_("متقاضی"),
    )

    # How to reach them: the whole point of the application is the conversation that follows
    contact_channel = models.CharField(_("راه ارتباطی"), max_length=12, choices=Channel.choices)
    contact_id = models.CharField(
        _("آیدی در آن بستر"), max_length=150, blank=True,
        help_text=_("اگر تماس تلفنی را انتخاب کرده‌اید، لازم نیست."),
    )

    pitch = models.TextField(
        _("چه کمکی می‌توانید بکنید"),
        help_text=_("کوتاه بنویسید: در چه کاری خوب هستید و دوست دارید چه کاری انجام دهید."),
    )

    # What kind of work — the three things the site actually offers
    can_teach = models.BooleanField(_("ساخت دوره آموزشی"), default=False)
    can_build = models.BooleanField(_("انجام پروژه"), default=False)
    can_advise = models.BooleanField(_("مشاوره"), default=False)

    domains = models.ManyToManyField(
        "domains.Domain", blank=True, related_name="collaboration_requests", verbose_name=_("حوزه‌ها"),
    )
    other_domain = models.CharField(_("حوزه‌ی دیگر"), max_length=150, blank=True)

    degree = models.CharField(_("مدرک تحصیلی"), max_length=12, choices=Degree.choices, blank=True)
    field_of_study = models.CharField(_("رشته‌ی تحصیلی"), max_length=150, blank=True)
    experience = models.TextField(_("سابقه‌ی کار"), blank=True)
    skills = models.TextField(_("مهارت‌ها"), blank=True)
    links = models.TextField(
        _("لینک‌ها"), blank=True,
        help_text=_("گیت‌هاب، لینکدین، نمونه‌کار — هر کدام در یک خط."),
    )

    status = models.CharField(_("وضعیت"), max_length=10, choices=Status.choices, default=Status.NEW)
    admin_note = models.TextField(_("یادداشت مدیر"), blank=True, help_text=_("متقاضی این را نمی‌بیند."))
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, editable=False,
        related_name="reviewed_collaborations", verbose_name=_("بررسی‌کننده"),
    )
    reviewed_at = models.DateTimeField(_("زمان بررسی"), null=True, blank=True, editable=False)

    created_at = models.DateTimeField(_("زمان ثبت"), auto_now_add=True)
    updated_at = models.DateTimeField(_("آخرین تغییر"), auto_now=True)

    class Meta:
        verbose_name = _("درخواست همکاری")
        verbose_name_plural = _("درخواست‌های همکاری")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.mobile_number} — {self.get_status_display()}"

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def is_editable(self):
        """Only until somebody starts reading it, so it cannot change under the reader."""
        return self.status == self.Status.NEW

    @property
    def wanted_work(self):
        labels = []
        for field in ("can_teach", "can_build", "can_advise"):
            if getattr(self, field):
                labels.append(self._meta.get_field(field).verbose_name)
        return "، ".join(str(label) for label in labels)

    def mark_reviewed(self, status, reviewer):
        self.status = status
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
        if status == self.Status.REJECTED:
            self.drop_files()

    def drop_files(self):
        """Somebody turned down should not have their documents kept on our disk."""
        for item in self.files.all():
            item.file.delete(save=False)
            item.delete()


class CollaborationFile(models.Model):
    """A CV or sample of work. Several are allowed; the form caps how many."""

    request = models.ForeignKey(
        CollaborationRequest, on_delete=models.CASCADE, related_name="files", verbose_name=_("درخواست"),
    )
    file = models.FileField(
        _("فایل"), upload_to="collaboration/%Y/%m/", storage=protected_storage,
        validators=[validate_file_extension, validate_file_size],
    )
    uploaded_at = models.DateTimeField(_("زمان بارگذاری"), auto_now_add=True)

    class Meta:
        verbose_name = _("فایل درخواست همکاری")
        verbose_name_plural = _("فایل‌های درخواست همکاری")
        ordering = ("uploaded_at",)

    def __str__(self):
        return self.name

    @property
    def name(self):
        return os.path.basename(self.file.name)
