from django.contrib.contenttypes.fields import GenericRelation
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .storage import protected_storage
from .validators import validate_aparat_url


class PublishState(models.Model):
    """Fields used by the approval workflow (same as Product)."""

    is_published = models.BooleanField(_("منتشر شده"), default=False)
    is_archived = models.BooleanField(_("حذف شده"), default=False)
    order = models.PositiveSmallIntegerField(_("ترتیب"), default=0, help_text=_("عدد کوچک‌تر، بالاتر نمایش داده می‌شود"))
    created_at = models.DateTimeField(_("تاریخ ایجاد"), auto_now_add=True)
    updated_at = models.DateTimeField(_("آخرین تغییر"), auto_now=True)

    change_requests = GenericRelation("approvals.ChangeRequest")  # deleted together with the item

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
        help_text=_("برای محصولات پولی. فقط خریداران می‌توانند ببینند."),
    )
    video_url = models.URLField(
        _("لینک ویدیو در آپارات"), blank=True, validators=[validate_aparat_url],
        help_text=_("فقط برای محصولات رایگان؛ ویدیوی آپارات برای همه قابل مشاهده است."),
    )
    duration_minutes = models.PositiveSmallIntegerField(_("مدت (دقیقه)"), null=True, blank=True)

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

    def clean(self):
        if self.video_file and self.video_url:
            raise ValidationError(_("یا فایل ویدیو آپلود کنید یا لینک آپارات بدهید، نه هر دو."))
        try:
            product = self.section.product
        except Section.DoesNotExist:  # no section chosen yet (the form shows that error)
            product = None
        if self.video_url and product is not None and not product.is_free:
            raise ValidationError({"video_url": _(
                "این محصول پولی است و ویدیوی آپارات برای همه قابل مشاهده است؛ ویدیو را آپلود کنید."
            )})


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