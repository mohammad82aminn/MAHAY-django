from django.contrib import admin, messages
from django.db import models
from django.db.models import Prefetch

from accounts.roles import is_site_admin

from . import services
from .models import ChangeRequest


class ApprovalModelAdmin(admin.ModelAdmin):
    """
    Admin behavior for content managed by domain managers.

    Site admins: every change is applied immediately.
    Domain managers:
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
        return is_site_admin(request.user)

    def get_queryset(self, request):
        pending = ChangeRequest.objects.filter(status=ChangeRequest.Status.PENDING)
        queryset = super().get_queryset(request).prefetch_related(
            Prefetch("change_requests", queryset=pending, to_attr="pending_requests")
        )
        if self.is_reviewer(request):
            return queryset
        return queryset.filter(**{f"{self.domain_field}__group__user": request.user})

    @admin.display(description="وضعیت")
    def state(self, obj):
        waiting = {request.action for request in getattr(obj, "pending_requests", [])}
        if obj.is_archived:
            return "حذف‌شده"
        if ChangeRequest.Action.ARCHIVE in waiting:
            return "منتشرشده (درخواست حذف در انتظار)"
        if obj.is_published:
            return "منتشرشده (تغییرات در انتظار)" if ChangeRequest.Action.UPDATE in waiting else "منتشرشده"
        return "در انتظار انتشار" if ChangeRequest.Action.CREATE in waiting else "پیش‌نویس"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # A manager can only attach items to their own domains (products: the domain; lessons: their sections...)
        first, _, rest = self.domain_field.partition("__")
        if db_field.name == first and not self.is_reviewer(request):
            lookup = f"{rest}__group__user" if rest else "group__user"
            kwargs["queryset"] = db_field.related_model._default_manager.filter(**{lookup: request.user})
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if not self.is_reviewer(request):
            fields = (*fields, *self.manager_readonly_fields)
        return fields

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