"""
The office managers' side (ستاد اداری): they watch how the staff work and report to the site admins.

Their own records are the reports below. The staff directory, the activity history and the review
timeline are views of what the site already keeps, given a place in the menu by proxy models.
"""
import os

from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.db import models
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from approvals.models import ReviewEvent
from content.storage import protected_storage
from inbox.validators import validate_file_extension, validate_file_size


class OfficeReport(models.Model):
    """A report from an office manager to the site admins, read and answered by them."""

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False, related_name="office_reports",
        verbose_name=_("نویسنده"),
    )
    title = models.CharField(_("عنوان"), max_length=200)
    body = models.TextField(_("متن گزارش"))
    period_from = models.DateField(_("از تاریخ"), null=True, blank=True)
    period_to = models.DateField(_("تا تاریخ"), null=True, blank=True)
    created_at = models.DateTimeField(_("زمان ارسال"), auto_now_add=True)

    read_at = models.DateTimeField(_("زمان خواندن"), null=True, blank=True, editable=False)
    read_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, editable=False,
        related_name="+", verbose_name=_("خوانده‌شده توسط"),
    )
    reply = models.TextField(_("پاسخ مدیر کل"), blank=True)
    replied_at = models.DateTimeField(_("زمان پاسخ"), null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("گزارش اداری")
        verbose_name_plural = _("گزارش‌های اداری")
        ordering = ("-created_at",)

    def __str__(self):
        return self.title


class OfficeReportFile(models.Model):
    report = models.ForeignKey(OfficeReport, on_delete=models.CASCADE, related_name="files", verbose_name=_("گزارش"))
    file = models.FileField(
        _("فایل"), upload_to="office/%Y/%m/", storage=protected_storage,
        validators=[validate_file_extension, validate_file_size],
    )
    uploaded_at = models.DateTimeField(_("زمان بارگذاری"), auto_now_add=True)

    class Meta:
        verbose_name = _("پیوست")
        verbose_name_plural = _("پیوست‌ها")

    def __str__(self):
        return self.name

    @property
    def name(self):
        return os.path.basename(self.file.name)


class StaffMember(User):
    """No table: «فهرست کارکنان», everyone who holds a role."""

    class Meta:
        proxy = True
        verbose_name = _("کارمند")
        verbose_name_plural = _("فهرست کارکنان")


class Activity(LogEntry):
    """No table: «سابقه‌ی کارها», everything the staff added, changed or removed in the panel."""

    class Meta:
        proxy = True
        verbose_name = _("کار ثبت‌شده")
        verbose_name_plural = _("سابقه‌ی کارها")


class ReviewTimeline(ReviewEvent):
    """No table: «روند بررسی محتوا», content made, sent, corrected, approved and turned down."""

    class Meta:
        proxy = True
        verbose_name = _("رویداد بررسی محتوا")
        verbose_name_plural = _("روند بررسی محتوا")


class Performance(User):
    """No table: «گزارش عملکرد», each staff member's figures over a period."""

    class Meta:
        proxy = True
        verbose_name = _("گزارش عملکرد")
        verbose_name_plural = _("گزارش عملکرد")
