"""
«درخواست‌های فنی» in the panel. What each person may do follows their role (support.services),
not per-model permissions, since the section is open to everyone on the staff.
"""
from django.contrib import admin
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from accounts.roles import TECH_ADMINS_GROUP, is_site_admin

from . import services
from .models import TechRequest, TechRequestFile, TechRequestMessage

ASKER_FIELDS = ("kind", "priority", "title", "description", "page_url")
TEAM_FIELDS = ("status", "assignee", "status_note")


def is_staff(request):
    return request.user.is_active and request.user.is_staff


class MessageInline(admin.StackedInline):
    """The conversation: anyone who can see the request may add to it; nothing is edited afterwards."""

    model = TechRequestMessage
    extra = 1
    fields = ("author", "created_at", "body")
    readonly_fields = ("author", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return is_staff(request) and (obj is None or self._takes_part(request, obj))

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return is_staff(request)

    @staticmethod
    def _takes_part(request, obj):
        return obj.requester_id == request.user.pk or services.works_on_requests(request.user)


class FileInline(admin.TabularInline):
    model = TechRequestFile
    extra = 1
    fields = ("file", "download", "uploaded_by", "uploaded_at")
    readonly_fields = ("download", "uploaded_by", "uploaded_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return MessageInline.has_add_permission(self, request, obj)

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return is_staff(request)

    _takes_part = staticmethod(MessageInline._takes_part)

    @admin.display(description=_("دانلود"))
    def download(self, obj):
        if not obj.pk:
            return "—"
        return format_html('<a href="{}">{}</a>', reverse("admin:support_techrequest_file", args=[obj.pk]), obj.name)


@admin.register(TechRequest)
class TechRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "kind", "priority", "status", "requester", "assignee", "updated_at")
    list_filter = ("status", "kind", "priority")
    search_fields = ("title", "description")
    inlines = (MessageInline, FileInline)
    counts_for_tech_admins = True  # the one red number that is the technical admins' own (see accounts.pending)

    def get_urls(self):
        page = self.admin_site.admin_view
        return [path("file/<int:pk>/", page(self.download), name="support_techrequest_file"), *super().get_urls()]

    def download(self, request, pk):
        attached = get_object_or_404(TechRequestFile.objects.select_related("request"), pk=pk)
        if not services.visible_requests(request.user).filter(pk=attached.request_id).exists():
            raise Http404
        return FileResponse(attached.file.open("rb"), as_attachment=True, filename=attached.name)

    def get_fieldsets(self, request, obj=None):
        fieldsets = [(None, {"fields": ASKER_FIELDS})]
        if obj is not None:
            fieldsets.insert(0, (_("وضعیت"), {"fields": ("requester", *TEAM_FIELDS, "created_at", "status_changed_at")}))
        return fieldsets

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        fixed = ["requester", "created_at", "status_changed_at"]
        if not services.works_on_requests(request.user):
            fixed += TEAM_FIELDS
        if obj.requester_id != request.user.pk or obj.status != TechRequest.Status.NEW:
            fixed += ASKER_FIELDS  # the question stays as it was asked once work on it has begun
        return fixed

    def get_queryset(self, request):
        return services.visible_requests(request.user).select_related("requester", "assignee")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "assignee":
            from accounts.models import User

            kwargs["queryset"] = User.objects.filter(groups__name=TECH_ADMINS_GROUP, is_active=True).distinct()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def pending_count(self, request):
        """New requests nobody has picked up, for the people who pick them up."""
        if not services.works_on_requests(request.user):
            return 0
        return TechRequest.objects.filter(status=TechRequest.Status.NEW).count()

    # --- Who may do what -------------------------------------------------------------

    def has_module_permission(self, request):
        return is_staff(request)

    def has_view_permission(self, request, obj=None):
        return is_staff(request) and (obj is None or services.visible_requests(request.user).filter(pk=obj.pk).exists())

    def has_add_permission(self, request):
        return is_staff(request)

    def has_change_permission(self, request, obj=None):
        if not is_staff(request):
            return False
        if obj is None:
            return True
        # The office follows along but takes no part; everyone else only in their own
        return obj.requester_id == request.user.pk or services.works_on_requests(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_site_admin(request.user)

    # --- Saving ----------------------------------------------------------------------

    def save_model(self, request, obj, form, change):
        moved = change and "status" in form.changed_data
        if not change:
            obj.requester = request.user
        if moved:
            obj.status_changed_at = timezone.now()
        super().save_model(request, obj, form, change)
        if not change:
            request._new_tech_request = obj
        elif moved or ("status_note" in form.changed_data and obj.status_note):
            services.announce_status(obj, request.user)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, TechRequestMessage):
                instance.author = request.user
            elif isinstance(instance, TechRequestFile):
                instance.uploaded_by = request.user
            instance.save()
            if isinstance(instance, TechRequestMessage) and change:
                services.announce_message(instance)
        formset.save_m2m()

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        new = getattr(request, "_new_tech_request", None)
        if new is not None:
            services.announce_new(new)  # after the files are in, so the team sees the whole thing
