"""
The کارپوشه: messages colleagues leave each other.

Only people who hold a role (members of any group — site admins, technical admins, the managers
of a domain) have one; customers never see it. A message is written once and sent to any mix of
people and groups; a group is expanded into its members at that moment, so somebody who joins
the group later does not inherit what was said before they arrived.

Nothing here is ever deleted. Archiving only hides a message from one side, so the other side
keeps its copy of what was agreed.
"""
import os

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from content.storage import protected_storage

from .validators import validate_file_extension, validate_file_size


class Message(models.Model):
    """One thing somebody sent. Who received it is in the Delivery rows."""

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="sent_messages", verbose_name=_("فرستنده"),
    )
    # Sent by the site itself (a rejection, a reminder): shown as «سامانه» and never answered,
    # unlike a message whose sender's account was later deleted
    from_system = models.BooleanField(_("از طرف سامانه"), default=False, editable=False)
    subject = models.CharField(_("موضوع"), max_length=200)
    body = models.TextField(_("متن پیام"))
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="replies", verbose_name=_("در پاسخ به"),
    )
    sender_archived_at = models.DateTimeField(_("بایگانی فرستنده"), null=True, blank=True)
    created_at = models.DateTimeField(_("زمان ارسال"), auto_now_add=True)

    class Meta:
        verbose_name = _("پیام کارپوشه")
        verbose_name_plural = _("پیام‌های کارپوشه")
        ordering = ("-created_at",)

    def __str__(self):
        return self.subject


class Delivery(models.Model):
    """
    One person's copy of a message. Read and archive state live here rather than on the message,
    so that one recipient opening it leaves it unread for everybody else.
    """

    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="deliveries", verbose_name=_("پیام"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="inbox_deliveries", verbose_name=_("گیرنده"),
    )
    read_at = models.DateTimeField(_("زمان خواندن"), null=True, blank=True)
    archived_at = models.DateTimeField(_("زمان بایگانی"), null=True, blank=True)

    class Meta:
        verbose_name = _("دریافت پیام")
        verbose_name_plural = _("دریافت‌های پیام")
        ordering = ("-message__created_at",)
        constraints = [
            models.UniqueConstraint(fields=("message", "user"), name="inbox_one_delivery_per_user"),
        ]
        indexes = [
            # The unread badge counts these on every page a staff member opens
            models.Index(fields=("user", "archived_at", "read_at"), name="inbox_unread_idx"),
        ]

    def __str__(self):
        return f"{self.message.subject} — {self.user}"

    @property
    def is_read(self):
        return self.read_at is not None

    def mark_read(self):
        if self.read_at is None:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at"])


class MessageFile(models.Model):
    """A file attached to a message. Stored out of reach of the web server; see the download view."""

    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="files", verbose_name=_("پیام"),
    )
    file = models.FileField(
        _("فایل"), upload_to="inbox/%Y/%m/", storage=protected_storage,
        validators=[validate_file_extension, validate_file_size],
    )
    uploaded_at = models.DateTimeField(_("زمان بارگذاری"), auto_now_add=True)

    class Meta:
        verbose_name = _("پیوست پیام")
        verbose_name_plural = _("پیوست‌های پیام")
        ordering = ("uploaded_at",)

    def __str__(self):
        return self.name

    @property
    def name(self):
        return os.path.basename(self.file.name)


class Reminder(models.Model):
    """
    A reminder that was already sent, so the hourly run never repeats it. The key names the
    waiting item and the moment it started waiting at that step: when it moves on and waits again,
    the key is new and it may be reminded again (see inbox.reminders).
    """

    key = models.CharField(_("کلید"), max_length=200, unique=True)
    sent_at = models.DateTimeField(_("زمان ارسال"), auto_now_add=True)

    class Meta:
        verbose_name = _("یادآوری ارسال‌شده")
        verbose_name_plural = _("یادآوری‌های ارسال‌شده")

    def __str__(self):
        return self.key
