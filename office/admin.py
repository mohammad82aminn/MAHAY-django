"""
The office pages: open to the office managers and the site admins only. Everything here is for
looking, not changing — except the office's own reports, and the site admins' replies to them.
"""
import csv

from django.contrib import admin
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from accounts.formatting import ltr
from accounts.roles import SITE_ADMINS_GROUP, is_office_manager, is_site_admin, role_label

from . import performance
from .models import Activity, OfficeReport, OfficeReportFile, Performance, ReviewTimeline, StaffMember

# The office watches the work, not the money and not anybody's messages
UNWATCHED_APPS = ("finance", "inbox", "office", "sessions", "admin", "contenttypes")


def sees_office(user):
    return is_office_manager(user) or is_site_admin(user)


class OfficeOnly:
    def has_module_permission(self, request):
        return sees_office(request.user)

    def has_view_permission(self, request, obj=None):
        return sees_office(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# --- Staff directory ----------------------------------------------------------------

@admin.register(StaffMember)
class StaffMemberAdmin(OfficeOnly, admin.ModelAdmin):
    list_display = ("full_name", "roles", "mobile", "email", "contact_handle", "last_login", "date_joined", "is_active")
    list_filter = ("groups", "is_active")
    search_fields = ("first_name", "last_name", "mobile_number", "email", "contact_handle")
    fields = ("full_name", "roles", "mobile", "email", "contact_handle", "last_login", "date_joined", "is_active")
    readonly_fields = fields

    def get_queryset(self, request):
        return StaffMember.objects.filter(is_staff=True).prefetch_related("groups")  # never the customers

    @admin.display(description=_("نام"), ordering="first_name")
    def full_name(self, obj):
        return obj.get_full_name() or "—"

    @admin.display(description=_("نقش‌ها"))
    def roles(self, obj):
        return role_label(obj)

    @admin.display(description=_("موبایل"), ordering="mobile_number")
    def mobile(self, obj):
        return ltr(obj.mobile_number)


# --- Activity -----------------------------------------------------------------------

@admin.register(Activity)
class ActivityAdmin(OfficeOnly, admin.ModelAdmin):
    list_display = ("action_time", "user", "what", "item", "details")
    list_filter = (("user", admin.RelatedOnlyFieldListFilter), "action_flag", "content_type", "action_time")
    search_fields = ("object_repr", "change_message")
    date_hierarchy = "action_time"
    fields = ("action_time", "user", "what", "content_type", "item", "details")
    readonly_fields = fields

    def get_queryset(self, request):
        return (
            Activity.objects.exclude(content_type__app_label__in=UNWATCHED_APPS)
            .select_related("user", "content_type")
        )

    @admin.display(description=_("کار"), ordering="action_flag")
    def what(self, obj):
        return {1: "افزودن", 2: "ویرایش", 3: "حذف"}.get(obj.action_flag, "—")

    @admin.display(description=_("مورد"))
    def item(self, obj):
        kind = obj.content_type.model_class()._meta.verbose_name if obj.content_type and obj.content_type.model_class() else ""
        return f"{kind}: {obj.object_repr}" if kind else obj.object_repr

    @admin.display(description=_("جزئیات"))
    def details(self, obj):
        return obj.get_change_message() or "—"


@admin.register(ReviewTimeline)
class ReviewTimelineAdmin(OfficeOnly, admin.ModelAdmin):
    list_display = ("created_at", "actor", "kind", "item", "short_note")
    list_filter = ("kind", ("actor", admin.RelatedOnlyFieldListFilter), "created_at")
    date_hierarchy = "created_at"
    fields = ("created_at", "actor", "kind", "item", "note", "changes")
    readonly_fields = fields

    def get_queryset(self, request):
        return ReviewTimeline.objects.select_related("actor", "change_request", "content_type")

    @admin.display(description=_("مورد"))
    def item(self, obj):
        if obj.change_request_id:
            return obj.change_request.object_repr
        return f"{obj.content_type} #{obj.object_id}"

    @admin.display(description=_("توضیح"))
    def short_note(self, obj):
        return (obj.note[:80] + "…") if len(obj.note) > 80 else (obj.note or "—")


# --- Performance --------------------------------------------------------------------

@admin.register(Performance)
class PerformanceAdmin(OfficeOnly, admin.ModelAdmin):
    def get_urls(self):
        return [path("", self.admin_site.admin_view(self.report_view), name="office_performance_changelist")]

    def report_view(self, request):
        if not sees_office(request.user):
            raise Http404
        period = request.GET.get("period")
        if period not in performance.PERIODS:
            period = performance.DEFAULT_PERIOD
        report = performance.build(period)
        if request.GET.get("export"):
            response = HttpResponse(content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = 'attachment; filename="performance.csv"'
            response.write("﻿")
            writer = csv.writer(response)
            writer.writerow(["نام", "نقش", *report["columns"]])
            for row in report["rows"]:
                writer.writerow([row["person"].get_full_name(), row["role"], *[value or 0 for value in row["values"]]])
            return response
        return render(request, "admin/office/performance.html", {
            **self.admin_site.each_context(request),
            **report,
            "title": _("گزارش عملکرد"), "opts": self.model._meta, "period": period,
            "periods": [(key, label) for key, (_days, label) in performance.PERIODS.items()],
        })


# --- Office reports -----------------------------------------------------------------

class ReportFileInline(admin.TabularInline):
    model = OfficeReportFile
    extra = 1
    fields = ("file", "download", "uploaded_at")
    readonly_fields = ("download", "uploaded_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return is_office_manager(request.user) and (obj is None or obj.read_at is None)

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return sees_office(request.user)

    @admin.display(description=_("دانلود"))
    def download(self, obj):
        if not obj.pk:
            return "—"
        return format_html('<a href="{}">{}</a>', reverse("admin:office_officereport_file", args=[obj.pk]), obj.name)


@admin.register(OfficeReport)
class OfficeReportAdmin(admin.ModelAdmin):
    """An office manager writes; the site admins read and answer. Nobody else sees them."""

    list_display = ("title", "author", "period", "created_at", "is_read", "replied")
    list_filter = ("created_at",)
    search_fields = ("title", "body")
    inlines = (ReportFileInline,)
    AUTHOR_FIELDS = ("title", "period_from", "period_to", "body")

    def get_urls(self):
        page = self.admin_site.admin_view
        return [path("file/<int:pk>/", page(self.download), name="office_officereport_file"), *super().get_urls()]

    def download(self, request, pk):
        attached = get_object_or_404(OfficeReportFile.objects.select_related("report"), pk=pk)
        if not self.get_queryset(request).filter(pk=attached.report_id).exists():
            raise Http404
        return FileResponse(attached.file.open("rb"), as_attachment=True, filename=attached.name)

    def get_queryset(self, request):
        queryset = OfficeReport.objects.select_related("author", "read_by")
        if is_site_admin(request.user):
            return queryset
        return queryset.filter(author=request.user)

    def get_fieldsets(self, request, obj=None):
        fieldsets = [(None, {"fields": self.AUTHOR_FIELDS})]
        if obj is not None:
            fieldsets.append((_("پاسخ مدیر کل"), {"fields": ("author", "created_at", "read_by", "read_at", "reply", "replied_at")}))
        return fieldsets

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        fixed = ["author", "created_at", "read_by", "read_at", "replied_at"]
        if not is_site_admin(request.user):
            fixed.append("reply")
        if obj.author_id != request.user.pk or obj.read_at is not None:
            fixed += self.AUTHOR_FIELDS  # once read, a report stays as it was sent
        return fixed

    def change_view(self, request, object_id, form_url="", extra_context=None):
        if request.method == "GET" and is_site_admin(request.user):
            OfficeReport.objects.filter(pk=object_id, read_at__isnull=True).update(
                read_at=timezone.now(), read_by=request.user,
            )
        return super().change_view(request, object_id, form_url, extra_context)

    def pending_count(self, request):
        """Reports no site admin has opened yet."""
        if not is_site_admin(request.user):
            return 0
        return OfficeReport.objects.filter(read_at__isnull=True).count()

    def has_module_permission(self, request):
        return sees_office(request.user)

    def has_view_permission(self, request, obj=None):
        return sees_office(request.user)

    def has_add_permission(self, request):
        return is_office_manager(request.user)

    def has_change_permission(self, request, obj=None):
        if is_site_admin(request.user):
            return True
        return is_office_manager(request.user) and (obj is None or obj.author_id == request.user.pk)

    def has_delete_permission(self, request, obj=None):
        return False  # a report once sent is part of the record

    def save_model(self, request, obj, form, change):
        if not change:
            obj.author = request.user
        replied = change and "reply" in form.changed_data and obj.reply
        if replied:
            obj.replied_at = timezone.now()
            if obj.read_at is None:
                obj.read_at, obj.read_by = timezone.now(), request.user
        super().save_model(request, obj, form, change)
        if not change:
            self._tell(list(self._site_admins()), f"گزارش اداری تازه: {obj.title}",
                       [f"از {obj.author.get_full_name() or obj.author.mobile_number}", "", obj.body[:500]], obj)
        elif replied:
            self._tell([obj.author], f"پاسخ به گزارش «{obj.title}»", [obj.reply[:1000]], obj)

    @staticmethod
    def _site_admins():
        from accounts.models import User

        return User.objects.filter(groups__name=SITE_ADMINS_GROUP, is_active=True).distinct()

    @staticmethod
    def _tell(people, subject, lines, report):
        from inbox import services as inbox

        if people:
            url = reverse("admin:office_officereport_change", args=[report.pk])
            inbox.send(None, subject[:200], "\n".join([*lines, "", url]), people)

    @admin.display(description=_("بازه"))
    def period(self, obj):
        if obj.period_from or obj.period_to:
            return f"{obj.period_from or '…'} تا {obj.period_to or '…'}"
        return "—"

    @admin.display(description=_("خوانده شد"), boolean=True)
    def is_read(self, obj):
        return obj.read_at is not None

    @admin.display(description=_("پاسخ داده شد"), boolean=True)
    def replied(self, obj):
        return bool(obj.reply)
