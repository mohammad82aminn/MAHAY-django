from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html, format_html_join

from accounts.roles import is_site_admin, sees_everything
from domains.access import is_manager, managed_domains, member_domains

from . import services
from .models import ChangeRequest


def display_value(field, value, change_request=None):
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
        if value and change_request is not None and str(value).startswith(f"{services.PENDING_FILES_DIR}/"):
            url = reverse("approvals:pending_file", args=[change_request.pk, field.name])
            return format_html('<a href="{}" target="_blank">مشاهده فایل جدید</a>', url)
        return value or "—"
    if isinstance(value, int):
        return f"{value:,}"  # prices: 1,800,000
    return "—" if value in (None, "") else value


@admin.register(ChangeRequest)
class ChangeRequestAdmin(admin.ModelAdmin):
    list_display = ("object_repr", "action", "status", "stage_label", "domain", "submitted_by", "submitted_at")
    list_filter = ("status", "stage", "action", "domain")
    search_fields = ("object_repr",)
    actions = ("approve_selected", "reject_selected")
    fields = decision_fields = (
        "target_link", "action", "stage", "domain", "submitted_by", "submitted_at",
        "changes_table", "status", "review_note", "reviewed_by", "reviewed_at",
    )

    # --- Access -------------------------------------------------------------------

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related("domain", "submitted_by", "content_type")
        if sees_everything(request.user):
            return queryset
        return queryset.filter(domain__in=member_domains(request.user))  # their domains' requests

    def pending_count(self, request):
        """
        Only what is waiting on the visitor's own desk: a site admin counts what reached them, a
        domain manager what their experts sent. Nobody is shown a red number they cannot clear.
        """
        waiting = self.get_queryset(request).filter(status=ChangeRequest.Status.PENDING)
        if is_site_admin(request.user):
            return waiting.filter(stage=ChangeRequest.Stage.ADMIN).count()
        return waiting.filter(stage=ChangeRequest.Stage.DOMAIN, domain__in=managed_domains(request.user)).count()

    def has_add_permission(self, request):
        return False  # requests are created by the system

    def has_delete_permission(self, request, obj=None):
        return False  # kept as history

    def has_change_permission(self, request, obj=None):
        """Site admins decide anything still open; a domain manager what waits on their desk."""
        if is_site_admin(request.user):
            return obj is None or obj.is_pending
        if obj is None:
            return managed_domains(request.user).exists()
        return self._on_managers_desk(request, obj)

    @staticmethod
    def _on_managers_desk(request, obj):
        return (obj.is_pending and obj.stage == ChangeRequest.Stage.DOMAIN
                and obj.domain is not None and is_manager(request.user, obj.domain))

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change=change, **kwargs)
        status = form.base_fields.get("status")
        if status is not None and not is_site_admin(request.user):
            # For a domain manager, agreeing means sending it on to the site admins, not publishing
            status.choices = [
                (ChangeRequest.Status.PENDING, "در انتظار بررسی"),
                (ChangeRequest.Status.APPROVED, "تأیید و ارسال برای مدیر کل"),
                (ChangeRequest.Status.REJECTED, "رد (برگشت به کارشناس)"),
            ]
        return form

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
            rows.append((field.verbose_name, display_value(field, old), display_value(field, new, obj)))
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
        # Asked of the stored request: the form has already set the new status on this copy
        if not self.has_change_permission(request, ChangeRequest.objects.get(pk=change_request.pk)):
            return False  # e.g. a manager's bulk action reaching a request that isn't on their desk
        try:
            if status == ChangeRequest.Status.APPROVED and not is_site_admin(request.user):
                services.forward(change_request, request.user, note)
                change_request.review_note = ""  # the note went into the history; the admin writes their own
                return True
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
        return super().get_actions(request) if self.has_change_permission(request) else {}

    @admin.display(description="مرحله", ordering="stage")
    def stage_label(self, obj):
        return obj.get_stage_display() if obj.is_pending else "—"