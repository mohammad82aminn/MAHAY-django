from django import forms
from django.apps import apps
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, Permission
from django.db.models import Count
from django.utils.translation import gettext_lazy as _

from .forms import AdminUserCreationForm, UserChangeForm
from .models import User
from .roles import DOMAIN_MANAGER_APPS, DOMAIN_MANAGER_FORBIDDEN, FULL_ACCESS_GROUPS, is_system_group
from .validators import DIGIT_MAP
from .models import LoginAttempt, User, VerificationCode

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserChangeForm
    add_form = AdminUserCreationForm

    list_display = ("mobile_number", "first_name", "last_name", "roles", "mobile_verified", "is_active")
    list_filter = ("mobile_verified", "is_active", "is_staff", "is_superuser", "groups")
    search_fields = ("mobile_number", "first_name", "last_name", "email")
    ordering = ("-date_joined",)
    readonly_fields = ("is_staff", "last_login", "date_joined")
    filter_horizontal = ("groups",)

    fieldsets = (
        (None, {"fields": ("mobile_number", "password")}),
        (_("اطلاعات شخصی"), {"fields": ("first_name", "last_name", "email")}),
        # Access is only given through groups (no per-user permissions); is_staff is set automatically
        (_("نقش‌ها و دسترسی"), {"fields": ("groups", "mobile_verified", "is_active", "is_staff", "is_superuser")}),
        (_("تاریخ‌ها"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("mobile_number", "email", "first_name", "last_name",
                       "usable_password", "password1", "password2"),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("groups")

    def get_readonly_fields(self, request, obj=None):
        # Only a superuser can create another superuser
        fields = super().get_readonly_fields(request, obj)
        if not getattr(request.user, "is_superuser", False):
            fields = (*fields, "is_superuser")
        return fields

    @admin.display(description=_("نقش‌ها"))
    def roles(self, obj):
        names = [group.name for group in obj.groups.all()]
        if obj.is_superuser:
           names.insert(0, "مالک سیستم")
        return "، ".join(names) or "کاربر عادی"

    def get_search_results(self, request, queryset, search_term):
        # Numbers are stored as +98912..., so "0912" or "۰۹۱۲" must be translated to match
        queryset, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        term = search_term.translate(DIGIT_MAP).strip()
        if term.isdigit() and term.startswith("0"):
            queryset |= self.model.objects.filter(mobile_number__startswith=f"+98{term[1:]}")
        return queryset, may_have_duplicates


@admin.register(VerificationCode)
class VerificationCodeAdmin(admin.ModelAdmin):
    """Read-only: helpful when a user says "the code doesn't arrive"."""

    list_display = ("mobile_number", "purpose", "created_at", "expires_at", "attempts", "used_at")
    list_filter = ("purpose", "created_at")
    search_fields = ("mobile_number",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    """Read-only: shows whether someone is trying to guess passwords."""

    list_display = ("mobile_number", "ip_address", "created_at")
    search_fields = ("mobile_number", "ip_address")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

# --- Groups -----------------------------------------------------------------------

PERMISSION_ACTIONS = {"add": "افزودن", "change": "ویرایش", "delete": "حذف", "view": "مشاهده"}


class PermissionChoiceField(forms.ModelMultipleChoiceField):
    """Shows permissions in Persian, e.g. "حوزه‌ها | ویرایش حوزه" instead of "Can change حوزه"."""

    def label_from_instance(self, obj):
        action = obj.codename.partition("_")[0]
        model = obj.content_type.model_class()
        if action in PERMISSION_ACTIONS and model is not None:
            app_name = apps.get_app_config(obj.content_type.app_label).verbose_name
            return f"{app_name} | {PERMISSION_ACTIONS[action]} {model._meta.verbose_name}"
        return str(obj)


admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin):
    """f obj.name == SITE_ADMINS_GROUP
    - Site admins group: always has every permission (read-only here).
    - Domain groups: site admins choose their permissions, limited to content apps (DOMAIN_MANAGER_APPS).
    - System groups can't be renamed or deleted here (they're managed through domains).
    """

    list_display = ("name", "group_type", "member_count")
    readonly_fields = ("site_admins_note",)
    actions = None  # no bulk delete: system groups must not be deleted by mistake

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("domain").annotate(_member_count=Count("user"))

    def get_fields(self, request, obj=None):
        if obj is not None and obj.name in FULL_ACCESS_GROUPS:
            return ("name", "site_admins_note")
        return ("name", "permissions")

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if obj is not None and is_system_group(obj):
            fields = (*fields, "name")
        return fields

    def formfield_for_manytomany(self, db_field, request=None, **kwargs):
        if db_field.name == "permissions":
            kwargs["form_class"] = PermissionChoiceField
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change=change, **kwargs)
        permissions = form.base_fields.get("permissions")
        if isinstance(permissions, PermissionChoiceField) and obj is not None and hasattr(obj, "domain"):
            # Domain groups: only content permissions (never users, groups, logs...)
            permissions.queryset = (
                Permission.objects.filter(content_type__app_label__in=DOMAIN_MANAGER_APPS)
                .exclude(codename__in=DOMAIN_MANAGER_FORBIDDEN)
                .select_related("content_type")
            )
        return form

    def has_delete_permission(self, request, obj=None):
        if obj is not None and is_system_group(obj):
            return False
        return super().has_delete_permission(request, obj)

    @admin.display(description=_("نوع"))
    def group_type(self, obj):
        if obj.name in FULL_ACCESS_GROUPS:
            return "دسترسی کامل"
        if hasattr(obj, "domain"):
            return f"مدیران حوزه ({obj.domain})"
        return "سایر"

    @admin.display(description=_("تعداد اعضا"), ordering="_member_count")
    def member_count(self, obj):
        return obj._member_count

    @admin.display(description=_("دسترسی‌ها"))
    def site_admins_note(self, obj):
        return "این گروه به‌صورت خودکار همه‌ی دسترسی‌های سایت را دارد و قابل تغییر نیست."