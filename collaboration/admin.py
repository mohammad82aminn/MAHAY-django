from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

from accounts.formatting import ltr

from .models import CollaborationFile, CollaborationRequest


class FileInline(admin.TabularInline):
    model = CollaborationFile
    extra = 0
    fields = ("download", "uploaded_at")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False  # files arrive with the application

    @admin.display(description=_("فایل"))
    def download(self, obj):
        if not obj.pk:
            return "—"
        return format_html('<a href="{}">{}</a>', reverse("collaboration:file", args=[obj.pk]), obj.name)


@admin.register(CollaborationRequest)
class CollaborationRequestAdmin(admin.ModelAdmin):
    list_display = ("applicant", "wanted_work", "domain_list", "status", "created_at")
    list_filter = ("status", "can_teach", "can_build", "can_advise", "domains", "created_at")
    search_fields = ("user__first_name", "user__last_name", "user__mobile_number", "pitch", "skills")
    date_hierarchy = "created_at"
    filter_horizontal = ("domains",)
    inlines = (FileInline,)
    # How they heard of us is the applicant's own answer, so nobody here edits it
    readonly_fields = ("user", "applicant_contact", "wanted_work", "heard_from", "heard_from_other",
                       "created_at", "updated_at", "reviewed_by", "reviewed_at")
    fieldsets = (
        (None, {"fields": ("user", "applicant_contact", "heard_from", "heard_from_other", "status",
                           "created_at", "updated_at")}),
        (_("معرفی"), {"fields": ("pitch", "wanted_work", "domains", "other_domain")}),
        (_("سابقه"), {"fields": ("degree", "field_of_study", "experience", "skills", "links")}),
        (_("بررسی"), {"fields": ("admin_note", "reviewed_by", "reviewed_at")}),
    )

    def has_add_permission(self, request):
        return False  # applications come from the site, not from here

    def pending_count(self, request):
        """Applications nobody has opened yet; moving one off «جدید» clears the mark."""
        return self.get_queryset(request).filter(status=CollaborationRequest.Status.NEW).count()

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user").prefetch_related("domains")

    def save_model(self, request, obj, form, change):
        was = CollaborationRequest.objects.filter(pk=obj.pk).values_list("status", flat=True).first()
        super().save_model(request, obj, form, change)
        if was != obj.status:
            # Rejecting drops the documents: keeping somebody's papers after turning them down
            # is a liability rather than an asset.
            obj.mark_reviewed(obj.status, request.user)

    @admin.display(description=_("متقاضی"), ordering="user__first_name")
    def applicant(self, obj):
        return obj.user.get_full_name() or obj.user.mobile_number

    @admin.display(description=_("راه تماس"))
    def applicant_contact(self, obj):
        if not obj.pk:
            return "—"
        rows = [
            (_("موبایل"), ltr(obj.user.mobile_number)),
            (_("ایمیل"), ltr(obj.user.email) if obj.user.email else "—"),
            (obj.get_contact_channel_display(), ltr(obj.contact_id) if obj.contact_id else "—"),
        ]
        return format_html_join("", "<div><b>{}:</b> {}</div>", rows)

    @admin.display(description=_("حوزه‌ها"))
    def domain_list(self, obj):
        names = [str(domain) for domain in obj.domains.all()]
        if obj.other_domain:
            names.append(f"{obj.other_domain} (سایر)")
        return "، ".join(names) or "—"
