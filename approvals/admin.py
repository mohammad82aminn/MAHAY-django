from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html, format_html_join

from accounts.roles import is_site_admin

from . import services
from .models import ChangeRequest


def display_value(field, value):
    """Human readable value for the changes table."""
    if isinstance(field, models.ManyToManyField):
        names = field.related_model._default_manager.filter(pk__in=value or [])
        return "، ".join(str(item) for item in names) or "—"
    if isinstance(field, models.ForeignKey):
        return str(field.related_model._default_manager.filter(pk=value).first() or "—")
    if isinstance(field, models.BooleanField):
        return "بله" if value else "خیر"
    if field.choices:
        return dict(field.flatchoices).get(value, value)
    if isinstance(field, models.FileField):
        return value or "—"
    if isinstance(value, int):
        return f"{value:,}"  # prices: 1,800,000
    return "—" if value in (None, "") else value


@admin.register(ChangeRequest)
class ChangeRequestAdmin(admin.ModelAdmin):
    list_display = ("object_repr", "action", "status", "domain", "submitted_by", "submitted_at")
    list_filter = ("status", "action", "domain")
    search_fields = ("object_repr",)
    actions = ("approve_selected", "reject_selected")
    fields = decision_fields = (
        "target_link", "action", "domain", "submitted_by", "submitted_at",
        "changes_table", "status", "review_note", "reviewed_by", "reviewed_at",
    )

    # --- Access -------------------------------------------------------------------

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related("domain", "submitted_by", "content_type")
        if is_site_admin(request.user):
            return queryset
        return queryset.filter(domain__group__user=request.user)  # managers: their domains' requests

    def has_add_permission(self, request):
        return False  # requests are created by the system

    def has_delete_permission(self, request, obj=None):
        return False  # kept as history

    def has_change_permission(self, request, obj=None):
        return is_site_admin(request.user) and (obj is None or obj.is_pending)

    def get_readonly_fields(self, request, obj=None):
        editable = ("status", "review_note")
        can_decide = self.has_change_permission(request, obj)
        return [name for name in self.decision_fields if name not in editable or not can_decide]

    # --- Display ------------------------------------------------------------------

    @admin.display(description="مورد")
    def target_link(self, obj):
        target = obj.target
        if target is None:
            return obj.object_repr
        try:
            url = reverse(f"admin:{obj.content_type.app_label}_{obj.content_type.model}_change", args=[obj.object_id])
        except NoReverseMatch:
            return obj.object_repr
        return format_html('<a href="{}">{}</a>', url, target)

    @admin.display(description="تغییرات پیشنهادی")
    def changes_table(self, obj):
        if obj.action != ChangeRequest.Action.UPDATE:
            return "—"
        target = obj.target
        model = obj.content_type.model_class()
        if model is None:
            return "—"
        rows = []
        for name, new in obj.data.items():
            field = model._meta.get_field(name)
            old = services.current_value(target, field) if target is not None else None
            rows.append((field.verbose_name, display_value(field, old), display_value(field, new)))
        body = format_html_join("", "<tr><td>{}</td><td>{}</td><td><strong>{}</strong></td></tr>", rows)
        return format_html(
            '<table><thead><tr><th>فیلد</th><th>مقدار فعلی</th><th>مقدار جدید</th></tr></thead>'
            "<tbody>{}</tbody></table>", body,
        )

    # --- Decisions ----------------------------------------------------------------

    def save_model(self, request, obj, form, change):
        old_status = ChangeRequest.objects.get(pk=obj.pk).status
        if old_status != ChangeRequest.Status.PENDING or obj.status == old_status:
            obj.status = old_status
            super().save_model(request, obj, form, change)  # only the note is saved
            return
        self._decide(request, obj, obj.status, obj.review_note)

    def _decide(self, request, change_request, status, note=""):
        try:
            if status == ChangeRequest.Status.APPROVED:
                services.approve(change_request, request.user, note)
            else:
                services.reject(change_request, request.user, note)
            return True
        except ValidationError as error:
            change_request.status = ChangeRequest.Status.PENDING
            self.message_user(
                request, f"«{change_request.object_repr}» قابل تأیید نیست: {'؛ '.join(error.messages)}", messages.ERROR,
            )
            return False

    @admin.action(description="تأیید درخواست‌های انتخاب‌شده")
    def approve_selected(self, request, queryset):
        done = sum(self._decide(request, item, ChangeRequest.Status.APPROVED) for item in queryset.filter(status="pending"))
        self.message_user(request, f"{done} درخواست تأیید شد.")

    @admin.action(description="رد درخواست‌های انتخاب‌شده")
    def reject_selected(self, request, queryset):
        done = sum(self._decide(request, item, ChangeRequest.Status.REJECTED) for item in queryset.filter(status="pending"))
        self.message_user(request, f"{done} درخواست رد شد.")

    def get_actions(self, request):
        return super().get_actions(request) if is_site_admin(request.user) else {}