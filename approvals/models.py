from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _


class ChangeRequest(models.Model):
    """
    A change by a domain manager that waits for a site admin's decision.
    The live object stays untouched until the request is approved.
    """

    class Action(models.TextChoices):
        CREATE = "create", _("انتشار")
        UPDATE = "update", _("ویرایش")
        ARCHIVE = "archive", _("حذف از فروشگاه")

    class Status(models.TextChoices):
        PENDING = "pending", _("در انتظار بررسی")
        APPROVED = "approved", _("تأیید شده")
        REJECTED = "rejected", _("رد شده")

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, verbose_name=_("نوع"))
    object_id = models.PositiveBigIntegerField(_("شناسه"))
    target = GenericForeignKey("content_type", "object_id")
    object_repr = models.CharField(_("عنوان"), max_length=200)
    domain = models.ForeignKey(
        "domains.Domain", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="change_requests", verbose_name=_("حوزه"),
    )

    action = models.CharField(_("نوع درخواست"), max_length=10, choices=Action.choices)
    status = models.CharField(_("وضعیت"), max_length=10, choices=Status.choices, default=Status.PENDING)
    data = models.JSONField(_("تغییرات"), default=dict, blank=True)

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="submitted_changes", verbose_name=_("ارسال‌کننده"),
    )
    submitted_at = models.DateTimeField(_("زمان ارسال"), auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_changes", verbose_name=_("بررسی‌کننده"),
    )
    reviewed_at = models.DateTimeField(_("زمان بررسی"), null=True, blank=True)
    review_note = models.TextField(_("توضیح مدیر"), blank=True, help_text=_("مثلاً دلیل رد درخواست"))

    class Meta:
        verbose_name = _("درخواست تأیید")
        verbose_name_plural = _("درخواست‌های تأیید")
        ordering = ("-submitted_at",)
        constraints = [
            # At most one open request of each kind per object (new edits replace the open one)
            models.UniqueConstraint(
                fields=("content_type", "object_id", "action"),
                condition=models.Q(status="pending"),
                name="approvals_one_pending_request_per_action",
            ),
        ]

    def __str__(self):
        return f"{self.Action(self.action).label}: {self.object_repr}"

    @property
    def is_pending(self):
        return self.status == self.Status.PENDING