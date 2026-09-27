from django.contrib.contenttypes.fields import GenericRelation
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from .storage import protected_storage
from .validators import validate_aparat_url
from .video import mp4_seconds


class PublishState(models.Model):
    """Fields used by the approval workflow (same as Product)."""

    is_published = models.BooleanField(_("منتشر شده"), default=False)
    is_archived = models.BooleanField(_("حذف شده"), default=False)
    order = models.PositiveSmallIntegerField(_("ترتیب"), default=0, help_text=_("عدد کوچک‌تر، بالاتر نمایش داده می‌شود"))
    # Who made it: an expert may change only their own unpublished work (see ApprovalModelAdmin).
    # Empty for what existed before this was recorded — only managers and site admins edit those.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False,
        related_name="+", verbose_name=_("سازنده"),
    )
    created_at = models.DateTimeField(_("تاریخ ایجاد"), auto_now_add=True)
    updated_at = models.DateTimeField(_("آخرین تغییر"), auto_now=True)

    change_requests = GenericRelation("approvals.ChangeRequest")  # deleted together with the item
    review_events = GenericRelation("approvals.ReviewEvent")

    class Meta:
        abstract = True
        ordering = ("order", "id")


class Section(PublishState):
    """A chapter of a course, or a part of a project (e.g. "معرفی"، "پیاده‌سازی"، "فایل‌ها")."""

    product = models.ForeignKey(
        "products.Product", on_delete=models.CASCADE, related_name="sections", verbose_name=_("محصول"),
    )
    title = models.CharField(_("عنوان بخش"), max_length=200)

    class Meta(PublishState.Meta):
        verbose_name = _("بخش (فصل)")
        verbose_name_plural = _("بخش‌ها (فصل‌ها)")

    def __str__(self):
        return f"{self.product} ← {self.title}"

    def approval_children(self):
        return Lesson.objects.filter(section=self)


class Lesson(PublishState):
    """One lesson: a video (uploaded or an Aparat link), a text and attached files. All parts are optional."""

    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="lessons", verbose_name=_("بخش"))
    title = models.CharField(_("عنوان درس"), max_length=200)
    body = models.TextField(_("متن توضیحی"), blank=True)
    video_file = models.FileField(
        _("فایل ویدیو"), upload_to="videos/%Y/%m/", storage=protected_storage, blank=True,
        validators=[FileExtensionValidator(["mp4"], message=_("فقط ویدیوی MP4 پذیرفته می‌شود."))],
        help_text=_("فقط MP4. مدت ویدیو خودکار از روی فایل خوانده می‌شود. فقط خریداران می‌توانند ببینند."),
    )
    video_url = models.URLField(
        _("لینک ویدیو در آپارات"), blank=True, validators=[validate_aparat_url],
        help_text=_("فقط برای محصولات رایگان؛ ویدیوی آپارات برای همه قابل مشاهده است."),
    )
    duration_minutes = models.PositiveSmallIntegerField(
        _("مدت ویدیوی آپارات (دقیقه)"), null=True, blank=True,
        help_text=_("فقط برای لینک آپارات. مدت ویدیوی آپلودشده خودکار حساب می‌شود."),
    )
    # What every total is summed from: read from the video file, or the minutes typed for an Aparat link
    duration_seconds = models.PositiveIntegerField(_("مدت (ثانیه)"), null=True, blank=True, editable=False)

    class Meta(PublishState.Meta):
        verbose_name = _("درس")
        verbose_name_plural = _("درس‌ها")

    def __str__(self):
        return f"{self.section} ← {self.title}"

    @property
    def product(self):
        return self.section.product

    def approval_children(self):
        return Attachment.objects.filter(lesson=self)

    @classmethod
    def from_db(cls, db, field_names, values):
        lesson = super().from_db(db, field_names, values)
        row = dict(zip(field_names, values))
        lesson._saved_video = (row["video_file"] or "") if "video_file" in row else None  # None: not loaded
        return lesson

    def video_changed(self):
        saved = getattr(self, "_saved_video", "")  # a new lesson has no saved video
        return saved is not None and (self.video_file.name or "") != saved

    def clean(self):
        if self.video_file and self.video_url:
            raise ValidationError(_("یا فایل ویدیو آپلود کنید یا لینک آپارات بدهید، نه هر دو."))
        if self.video_file:
            self.duration_minutes = None  # the file itself says how long it is
            if self.video_changed():
                self._video_seconds = mp4_seconds(self.video_file)
                if self._video_seconds is None:
                    raise ValidationError({"video_file": _(
                        "مدت این ویدیو خوانده نشد؛ فایل MP4 سالم آپلود کنید."
                    )})
        try:
            product = self.section.product
        except Section.DoesNotExist:  # no section chosen yet (the form shows that error)
            product = None
        if self.video_url and product is not None and not product.is_free:
            raise ValidationError({"video_url": _(
                "این محصول پولی است و ویدیوی آپارات برای همه قابل مشاهده است؛ ویدیو را آپلود کنید."
            )})

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is None or {"video_file", "duration_minutes"} & set(update_fields):
            if self.video_file:
                if self.video_changed() or self.duration_seconds is None:
                    seconds = getattr(self, "_video_seconds", None)  # already read by clean()
                    self.duration_seconds = seconds if seconds is not None else mp4_seconds(self.video_file)
            else:
                self.duration_seconds = self.duration_minutes * 60 if self.duration_minutes else None
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "duration_seconds"}
        super().save(*args, **kwargs)
        self._saved_video, self._video_seconds = self.video_file.name or "", None


class Attachment(PublishState):
    """A file of a lesson: PDF, source code, README, ..."""

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="attachments", verbose_name=_("درس"))
    title = models.CharField(_("عنوان فایل"), max_length=200)
    file = models.FileField(_("فایل"), upload_to="attachments/%Y/%m/", storage=protected_storage)

    class Meta(PublishState.Meta):
        verbose_name = _("فایل ضمیمه")
        verbose_name_plural = _("فایل‌های ضمیمه")

    def __str__(self):
        return self.title

    @property
    def product(self):
        return self.lesson.section.product

    

class ProductFile(PublishState):
    """
    A file for the whole course or project (a handbook, the full source code...), listed on its
    table of contents. A file of a single lesson is an Attachment instead.
    """

    product = models.ForeignKey(
        "products.Product", on_delete=models.CASCADE, related_name="companion_files", verbose_name=_("محصول"),
    )
    title = models.CharField(_("عنوان فایل"), max_length=200)
    file = models.FileField(_("فایل"), upload_to="product_files/%Y/%m/", storage=protected_storage)

    class Meta(PublishState.Meta):
        verbose_name = _("فایل همراه")
        verbose_name_plural = _("فایل‌های همراه")

    def __str__(self):
        return self.title


class LessonProgress(models.Model):
    """
    How much of a lesson a user has watched. Saved automatically by the player
    (see static/js/player.js), so the user can continue where they stopped.
    """

    COMPLETE_RATIO = 0.9  # watching 90% counts as finished (the end is usually just credits)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_progress", verbose_name=_("کاربر"),
    )
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="progress", verbose_name=_("درس"))
    position_seconds = models.PositiveIntegerField(_("محل توقف (ثانیه)"), default=0)
    duration_seconds = models.PositiveIntegerField(_("مدت ویدیو (ثانیه)"), default=0)
    is_completed = models.BooleanField(_("تمام‌شده"), default=False)
    updated_at = models.DateTimeField(_("آخرین تماشا"), auto_now=True)

    class Meta:
        verbose_name = _("پیشرفت درس")
        verbose_name_plural = _("پیشرفت درس‌ها")
        ordering = ("-updated_at",)
        constraints = [
            models.UniqueConstraint(fields=("user", "lesson"), name="content_one_progress_per_lesson"),
        ]

    def __str__(self):
        return f"{self.user} — {self.lesson.title} ({self.percent}%)"

    @property
    def percent(self):
        if self.is_completed:
            return 100
        if not self.duration_seconds:
            return 0
        return min(99, round(self.position_seconds * 100 / self.duration_seconds))

    def watched(self, position, duration):
        """Called while the video plays. Completion is never taken back."""
        self.position_seconds = max(0, int(position))
        self.duration_seconds = max(self.duration_seconds, int(duration))
        if self.duration_seconds and self.position_seconds >= self.duration_seconds * self.COMPLETE_RATIO:
            self.is_completed = True
        self.save()