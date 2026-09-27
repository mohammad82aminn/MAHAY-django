"""
«درخواست‌های فنی»: how anyone on the staff asks the technical team for something — a fault to fix,
a feature to add, a question — and follows it to the end.
"""
import os

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from content.storage import protected_storage
from inbox.validators import validate_file_extension, validate_file_size


class TechRequest(models.Model):
    class Kind(models.TextChoices):
        BUG = "bug", _("خطا")
        FEATURE = "feature", _("قابلیت جدید")
        QUESTION = "question", _("سؤال")

    class Priority(models.TextChoices):
        NORMAL = "normal", _("عادی")
        URGENT = "urgent", _("فوری")

    class Status(models.TextChoices):
        NEW = "new", _("جدید")
        IN_PROGRESS = "in_progress", _("در حال انجام")
        DONE = "done", _("انجام شد")
        REJECTED = "rejected", _("رد شد")

    kind = models.CharField(_("نوع"), max_length=10, choices=Kind.choices, default=Kind.BUG)
    priority = models.CharField(_("فوریت"), max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    title = models.CharField(_("عنوان"), max_length=200)
    description = models.TextField(
        _("شرح"), help_text=_("چه کردید، چه انتظار داشتید و چه دیدید. برای قابلیت جدید: چه چیزی و چرا."),
    )
    page_url = models.CharField(
        _("آدرس صفحه"), max_length=500, blank=True, help_text=_("اختیاری: صفحه‌ای که مشکل در آن دیده شد."),
    )

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False, related_name="tech_requests",
        verbose_name=_("درخواست‌دهنده"),
    )
    status = models.CharField(_("وضعیت"), max_length=12, choices=Status.choices, default=Status.NEW)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name=_("مسئول"), help_text=_("یکی از مدیران فنی."),
    )
    status_note = models.TextField(
        _("توضیح وضعیت"), blank=True, help_text=_("مثلاً چه چیزی انجام شد یا چرا رد شد؛ درخواست‌دهنده می‌بیند."),
    )
    status_changed_at = models.DateTimeField(_("زمان تغییر وضعیت"), default=timezone.now, editable=False)
    created_at = models.DateTimeField(_("زمان ثبت"), auto_now_add=True)
    updated_at = models.DateTimeField(_("آخرین تغییر"), auto_now=True)

    class Meta:
        verbose_name = _("درخواست فنی")
        verbose_name_plural = _("درخواست‌های فنی")
        ordering = ("-created_at",)

    def __str__(self):
        return f"#{self.pk} {self.title}"

    @property
    def is_open(self):
        return self.status in (self.Status.NEW, self.Status.IN_PROGRESS)


class TechRequestMessage(models.Model):
    """The conversation under a request, between whoever asked and the technical team."""

    request = models.ForeignKey(TechRequest, on_delete=models.CASCADE, related_name="messages", verbose_name=_("درخواست"))
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False, related_name="+",
        verbose_name=_("نویسنده"),
    )
    body = models.TextField(_("متن"))
    created_at = models.DateTimeField(_("زمان"), auto_now_add=True)

    class Meta:
        verbose_name = _("پیام")
        verbose_name_plural = _("گفتگو")
        ordering = ("created_at", "id")

    def __str__(self):
        return self.body[:60]


class TechRequestFile(models.Model):
    """A screenshot or file with a request. Kept in the protected storage, opened only through a check."""

    request = models.ForeignKey(TechRequest, on_delete=models.CASCADE, related_name="files", verbose_name=_("درخواست"))
    file = models.FileField(
        _("فایل"), upload_to="support/%Y/%m/", storage=protected_storage,
        validators=[validate_file_extension, validate_file_size],
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False, related_name="+",
        verbose_name=_("بارگذاری‌کننده"),
    )
    uploaded_at = models.DateTimeField(_("زمان بارگذاری"), auto_now_add=True)

    class Meta:
        verbose_name = _("فایل")
        verbose_name_plural = _("فایل‌ها و تصویرها")
        ordering = ("uploaded_at",)

    def __str__(self):
        return self.name

    @property
    def name(self):
        return os.path.basename(self.file.name)
