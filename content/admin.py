from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from approvals.admin_base import ApprovalModelAdmin
from .models import Attachment, Lesson, LessonProgress, ProductFile, Section


@admin.register(Section)
class SectionAdmin(ApprovalModelAdmin):
    domain_field = "product__primary_domain"
    list_display = ("title", "product", "order", "state")
    list_filter = ("product__primary_domain", "product")
    search_fields = ("title", "product__title")
    fields = ("product", "title", "order", "lessons_link", "is_published", "is_archived")
    readonly_fields = ("lessons_link",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("product")

    @admin.display(description=_("درس‌ها"))
    def lessons_link(self, obj):
        if not obj.pk:
            return "بعد از ذخیره، درس‌ها را اضافه کنید."
        add_url = f"{reverse('admin:content_lesson_add')}?section={obj.pk}"
        list_url = f"{reverse('admin:content_lesson_changelist')}?section__id__exact={obj.pk}"
        return format_html('<a href="{}">{} درس</a> &nbsp;|&nbsp; <a href="{}">+ افزودن درس</a>',
                           list_url, obj.lessons.count(), add_url)


@admin.register(Lesson)
class LessonAdmin(ApprovalModelAdmin):
    domain_field = "section__product__primary_domain"
    list_display = ("title", "section", "order", "video_type", "state")
    list_filter = ("section__product__primary_domain", "section__product")
    search_fields = ("title", "section__title", "section__product__title")
    fields = (
        "section", "title", "order", "body", "video_file", "video_preview", "duration_display",
        "video_url", "duration_minutes", "attachments_link", "is_published", "is_archived",
    )
    readonly_fields = ("video_preview", "duration_display", "attachments_link")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("section__product")

    @admin.display(description=_("ویدیو"))
    def video_type(self, obj):
        if obj.video_file:
            return "آپلود شده"
        return "آپارات" if obj.video_url else "—"

    @admin.display(description=_("پیش‌نمایش ویدیو"))
    def video_preview(self, obj):
        if not obj.pk or not obj.video_file:
            return "—"
        url = reverse("content:protected_file", args=["video", obj.pk])
        return format_html('<a href="{}" target="_blank">مشاهده ویدیو</a>', url)

    @admin.display(description=_("مدت درس"))
    def duration_display(self, obj):
        if not obj.pk or not obj.duration_seconds:
            return "مدت ویدیوی آپلودشده بعد از ذخیره خودکار خوانده می‌شود."
        minutes, seconds = divmod(obj.duration_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"

    @admin.display(description=_("فایل‌های ضمیمه"))
    def attachments_link(self, obj):
        if not obj.pk:
            return "بعد از ذخیره، فایل‌ها را اضافه کنید."
        add_url = f"{reverse('admin:content_attachment_add')}?lesson={obj.pk}"
        list_url = f"{reverse('admin:content_attachment_changelist')}?lesson__id__exact={obj.pk}"
        return format_html('<a href="{}">{} فایل</a> &nbsp;|&nbsp; <a href="{}">+ افزودن فایل</a>',
                           list_url, obj.attachments.count(), add_url)


@admin.register(Attachment)
class AttachmentAdmin(ApprovalModelAdmin):
    domain_field = "lesson__section__product__primary_domain"
    list_display = ("title", "lesson", "order", "state")
    list_filter = ("lesson__section__product__primary_domain", "lesson__section__product")
    search_fields = ("title", "lesson__title")
    fields = ("lesson", "title", "file", "file_link", "order", "is_published", "is_archived")
    readonly_fields = ("file_link",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("lesson__section__product")

    @admin.display(description=_("دانلود"))
    def file_link(self, obj):
        if not obj.pk or not obj.file:
            return "—"
        return format_html('<a href="{}">دانلود فایل</a>', reverse("content:protected_file", args=["attachment", obj.pk]))

    

@admin.register(ProductFile)
class ProductFileAdmin(ApprovalModelAdmin):
    domain_field = "product__primary_domain"
    list_display = ("title", "product", "order", "state")
    list_filter = ("product__primary_domain", "product")
    search_fields = ("title", "product__title")
    fields = ("product", "title", "file", "file_link", "order", "is_published", "is_archived")
    readonly_fields = ("file_link",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("product")

    @admin.display(description=_("دانلود"))
    def file_link(self, obj):
        if not obj.pk or not obj.file:
            return "—"
        return format_html('<a href="{}">دانلود فایل</a>', reverse("content:protected_file", args=["product_file", obj.pk]))


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    """Read-only: written by the player, useful for support questions."""

    list_display = ("user", "lesson", "percent_display", "is_completed", "updated_at")
    list_filter = ("is_completed", "lesson__section__product")
    search_fields = ("user__mobile_number", "lesson__title")
    readonly_fields = ("user", "lesson", "position_seconds", "duration_seconds", "is_completed", "updated_at")

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "lesson__section__product")

    @admin.display(description=_("درصد"))
    def percent_display(self, obj):
        return f"{obj.percent}٪"