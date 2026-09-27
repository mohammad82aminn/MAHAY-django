from django.contrib import admin, messages
from django.db import models
from django.db.models import Prefetch
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

from accounts.roles import is_site_admin, sees_everything
from domains.access import is_manager, member_domains

from . import services
from .models import ChangeRequest, ReviewEvent


class ApprovalModelAdmin(admin.ModelAdmin):
    """
    Admin behavior for content managed by domain managers.

    Site admins: every change is applied immediately.
    Experts see their domain's content and may change or delete only their own unpublished work.
    Domain managers (and experts for their own drafts):
      - see and edit only items of their own domains
      - new item          -> saved hidden + "publish" request
      - edit draft item   -> saved (nobody sees it yet) + "publish" request is refreshed
      - edit published    -> nothing changes on the site; the edit waits as an "update" request
      - delete published  -> "archive" request (never deleted: buyers must keep access)
      - delete draft      -> deleted (nobody has seen or bought it)
    """

    domain_field = "primary_domain"  # path from the model to its owner Domain
    manager_readonly_fields = ("is_published", "is_archived")

    # --- Who sees what -------------------------------------------------------------

    def is_reviewer(self, request):
        """Decides: publishes, and changes things straight away."""
        return is_site_admin(request.user)

    def sees_all(self, request):
        """Is shown every domain's items (the technical admins too, read-only by their permissions)."""
        return sees_everything(request.user)

    def get_queryset(self, request):
        pending = ChangeRequest.objects.filter(status=ChangeRequest.Status.PENDING)
        queryset = super().get_queryset(request).prefetch_related(
            Prefetch("change_requests", queryset=pending, to_attr="pending_requests")
        )
        if self.sees_all(request):
            return queryset
        return queryset.filter(**{f"{self.domain_field}__in": member_domains(request.user)})

    @admin.display(description="وضعیت")
    def state(self, obj):
        waiting = {request.action: request for request in getattr(obj, "pending_requests", [])}
        if obj.is_archived:
            return "حذف‌شده"
        if ChangeRequest.Action.ARCHIVE in waiting:
            return "منتشرشده (درخواست حذف در انتظار)"
        if obj.is_published:
            return "منتشرشده (تغییرات در انتظار)" if ChangeRequest.Action.UPDATE in waiting else "منتشرشده"
        new = waiting.get(ChangeRequest.Action.CREATE)
        return new.get_stage_display() if new is not None else "پیش‌نویس"

    # --- Who may change what -------------------------------------------------------

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self._may_touch(request, obj)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and self._may_touch(request, obj)

    def _may_touch(self, request, obj):
        """
        A domain manager changes anything of their domain (published things through a request);
        an expert only what they made themselves and nobody has published yet. Everyone else in
        the domain gets the page read-only.
        """
        if obj is None or self.is_reviewer(request):
            return True
        if is_manager(request.user, self.get_domain(obj)):
            return True
        return not obj.is_published and not obj.is_archived and obj.created_by_id == request.user.pk

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # A manager can only attach items to their own domains (products: the domain; lessons: their sections...)
        first, _, rest = self.domain_field.partition("__")
        if db_field.name == first and not self.is_reviewer(request):
            lookup = f"{rest}__in" if rest else "pk__in"
            kwargs["queryset"] = db_field.related_model._default_manager.filter(**{lookup: member_domains(request.user)})
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        fields = (*super().get_readonly_fields(request, obj), "review_history")
        if not self.is_reviewer(request):
            fields = (*fields, *self.manager_readonly_fields)
        return fields

    def get_fieldsets(self, request, obj=None):
        fieldsets = [
            (name, {**options, "fields": [f for f in options["fields"] if f != "review_history"]})
            for name, options in super().get_fieldsets(request, obj)
        ]
        if obj is not None:
            fieldsets.append((_("سابقه‌ی بررسی"), {"fields": ("review_history",)}))
        return fieldsets

    @admin.display(description=_("سابقه"))
    def review_history(self, obj):
        """Who made it, sent it, corrected it, approved or turned it down — and what they said."""
        events = obj.review_events.select_related("actor") if obj.pk else []
        rows = []
        for event in events:
            who = event.actor.get_full_name() or event.actor.mobile_number if event.actor else "—"
            changes = format_html_join(
                "", "<div>• {}: <del>{}</del> ← <b>{}</b></div>",
                ((item["field"], item["old"], item["new"]) for item in event.changes),
            )
            note = format_html("<div>«{}»</div>", event.note) if event.note else ""
            rows.append((event.created_at.strftime("%Y/%m/%d %H:%M"), who, event.get_kind_display(), note, changes))
        if not rows:
            return "—"
        return format_html_join(
            "", '<div style="margin-bottom:.6rem"><b>{} — {}:</b> {}{}{}</div>', rows,
        )

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)  # bulk delete would skip the approval rules
        return actions

    def get_domain(self, obj):
        value = obj
        for part in self.domain_field.split("__"):
            value = getattr(value, part)
        return value

    # --- Show pending edits in the form ---------------------------------------------

    def get_form(self, request, obj=None, change=False, **kwargs):
        form_class = super().get_form(request, obj, change=change, **kwargs)
        if obj is None or self.is_reviewer(request):
            return form_class
        pending = services.pending_request(obj, ChangeRequest.Action.UPDATE)
        if pending is None:
            return form_class

        # The manager continues from their pending version, not from the live one (files are shown live)
        meta = obj._meta
        overlay = {
            name: value for name, value in pending.data.items()
            if not isinstance(meta.get_field(name), models.FileField)
        }

        class PendingForm(form_class):
            def __init__(self, *args, **form_kwargs):
                super().__init__(*args, **form_kwargs)
                for name, value in overlay.items():
                    if name in self.fields:
                        self.initial[name] = value

        return PendingForm

    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = self.get_object(request, object_id)
        if request.method == "GET" and obj is not None:
            if services.pending_request(obj, ChangeRequest.Action.UPDATE):
                self.message_user(request, "این مورد تغییراتی دارد که منتظر تأیید مدیر کل است.", messages.WARNING)
            if services.pending_request(obj, ChangeRequest.Action.ARCHIVE):
                self.message_user(request, "درخواست حذف این مورد منتظر تأیید مدیر کل است.", messages.WARNING)
        return super().change_view(request, object_id, form_url, extra_context)

    # --- Saving -------------------------------------------------------------------

    def save_model(self, request, obj, form, change):
        if not change and hasattr(obj, "created_by_id") and obj.created_by_id is None:
            obj.created_by = request.user

        if self.is_reviewer(request):
            super().save_model(request, obj, form, change)
            services.close_answered_requests(obj, request.user)
            return

        live = type(obj).objects.get(pk=obj.pk) if change else None

        if live is None or not live.is_published:
            # New item or draft: save it hidden and (re)send it for publishing
            obj.is_published = False
            if live is not None and live.created_by_id != request.user.pk:
                self._record_correction(request, live, form)
            super().save_model(request, obj, form, change)
            services.submit(obj, ChangeRequest.Action.CREATE, request.user, self.get_domain(obj))
            setattr(request, "_approval_message", "ذخیره شد و برای انتشار به مدیر کل ارسال شد.")
            return

        # Published item: the site keeps showing the live version until approval
        changes = services.form_changes(form, live)
        old = services.pending_request(live, ChangeRequest.Action.UPDATE)
        if old is not None:
            for name, value in old.data.items():  # keep a waiting file if it wasn't touched this time
                field = live._meta.get_field(name)
                if isinstance(field, models.FileField) and name not in changes and name not in form.changed_data:
                    changes[name] = value

        if changes:
            services.submit(live, ChangeRequest.Action.UPDATE, request.user, self.get_domain(live), changes)
            setattr(request, "_approval_message", "تغییرات برای تأیید به مدیر کل ارسال شد. تا آن زمان نسخه‌ی فعلی نمایش داده می‌شود.")
        else:
            services.withdraw(live, ChangeRequest.Action.UPDATE)
            setattr(request, "_approval_message", "تغییری نسبت به نسخه‌ی منتشرشده وجود ندارد.")
        setattr(request, "_approval_deferred", True)

    def _record_correction(self, request, live, form):
        """A domain manager changed someone else's draft: the author sees exactly what and how."""
        changes = []
        for name in form.changed_data:
            try:
                field = live._meta.get_field(name)
            except Exception:  # a form-only field
                continue
            old = getattr(live, name).all() if isinstance(field, models.ManyToManyField) else getattr(live, name)
            changes.append({
                "field": str(field.verbose_name),
                "old": services.describe(field, old),
                "new": services.describe(field, form.cleaned_data.get(name)),
            })
        if changes:
            services.record(live, ReviewEvent.Kind.EDITED, request.user, changes=changes)

    def save_related(self, request, form, formsets, change):
        if getattr(request, "_approval_deferred", False):
            return  # many-to-many changes are inside the pending request too
        super().save_related(request, form, formsets, change)

    def message_user(self, request, message, level=messages.INFO, *args, **kwargs):
        # Replace Django's "changed successfully" with the approval message
        custom = getattr(request, "_approval_message", None)
        if custom and level == messages.SUCCESS:
            message, level = custom, messages.INFO
            setattr(request, "_approval_message", None)
        super().message_user(request, message, level, *args, **kwargs)

    # --- Deleting -----------------------------------------------------------------

    def get_deleted_objects(self, objs, request):
        # A draft's approval requests are removed with it; nobody needs "delete request" permission for that
        deleted, model_count, perms_needed, protected = super().get_deleted_objects(objs, request)
        perms_needed.discard(ChangeRequest._meta.verbose_name)
        return deleted, model_count, perms_needed, protected

    def delete_model(self, request, obj):
        if not obj.is_published:
            super().delete_model(request, obj)  # draft: nobody has seen or bought it
        elif self.is_reviewer(request):
            obj.is_archived = True
            obj.save(update_fields=["is_archived"])
            setattr(request, "_approval_message", "این مورد از فروشگاه برداشته شد (خریداران همچنان دسترسی دارند).")
        else:
            services.submit(obj, ChangeRequest.Action.ARCHIVE, request.user, self.get_domain(obj))
            setattr(request, "_approval_message", "درخواست حذف برای تأیید به مدیر کل ارسال شد.")