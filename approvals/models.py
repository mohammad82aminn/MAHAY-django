from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class ChangeRequest(models.Model):
    """
    A change that waits for a decision. The live object stays untouched until it is approved.

    New content from an expert passes two desks: its domain's managers first («منتظر مدیر حوزه»),
    who may correct it and send it on, then the site admins («منتظر مدیر کل»), who publish it.
    Work from a domain manager, edits and removals of published content (which only managers may
    ask for), and anything from a domain with no manager yet start at the site admins' desk.
    """

    class Action(models.TextChoices):
        CREATE = "create", _("انتشار")
        UPDATE = "update", _("ویرایش")
        ARCHIVE = "archive", _("حذف از فروشگاه")

    class Status(models.TextChoices):
        PENDING = "pending", _("در انتظار بررسی")
        APPROVED = "approved", _("تأیید شده")
        REJECTED = "rejected", _("رد شده")

    class Stage(models.TextChoices):
        DOMAIN = "domain", _("منتظر مدیر حوزه")
        ADMIN = "admin", _("منتظر مدیر کل")

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
    stage = models.CharField(_("مرحله"), max_length=10, choices=Stage.choices, default=Stage.ADMIN)
    stage_since = models.DateTimeField(_("زمان رسیدن به این مرحله"), default=timezone.now, editable=False)
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

class ReviewEvent(models.Model):
    """
    One step in the life of a piece of content: sent for review, corrected by a domain manager,
    sent on, approved, turned down. Shown on the item's own page, so the expert who made it can
    see what happened to it and why, and kept after the request itself is closed.
    """

    class Kind(models.TextChoices):
        SUBMITTED = "submitted", _("ارسال برای بررسی")
        EDITED = "edited", _("اصلاح توسط مدیر حوزه")
        FORWARDED = "forwarded", _("تأیید مدیر حوزه و ارسال برای مدیر کل")
        APPROVED = "approved", _("تأیید نهایی")
        REJECTED = "rejected", _("رد")

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, verbose_name=_("نوع"))
    object_id = models.PositiveBigIntegerField(_("شناسه"))
    target = GenericForeignKey("content_type", "object_id")
    change_request = models.ForeignKey(
        ChangeRequest, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="events", verbose_name=_("درخواست تأیید"),
    )
    kind = models.CharField(_("رویداد"), max_length=10, choices=Kind.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="review_events", verbose_name=_("انجام‌دهنده"),
    )
    note = models.TextField(_("توضیح"), blank=True)
    # For an edit: [{"field": label, "old": text, "new": text}, ...]
    changes = models.JSONField(_("تغییرات"), default=list, blank=True)
    created_at = models.DateTimeField(_("زمان"), auto_now_add=True)

    class Meta:
        verbose_name = _("رویداد بررسی")
        verbose_name_plural = _("سابقه‌ی بررسی")
        ordering = ("created_at", "id")
        indexes = [models.Index(fields=("content_type", "object_id"))]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.created_at:%Y-%m-%d}"
