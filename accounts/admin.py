from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .forms import AdminUserCreationForm, UserChangeForm
from .models import User
from .validators import DIGIT_MAP


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserChangeForm
    add_form = AdminUserCreationForm

    list_display = ("mobile_number", "first_name", "last_name", "email", "is_staff", "is_active")
    list_filter = ("is_staff", "is_superuser", "is_active", "groups")
    search_fields = ("mobile_number", "first_name", "last_name", "email")
    ordering = ("-date_joined",)
    readonly_fields = ("last_login", "date_joined")
    filter_horizontal = ("groups", "user_permissions")

    fieldsets = (
        (None, {"fields": ("mobile_number", "password")}),
        (_("اطلاعات شخصی"), {"fields": ("first_name", "last_name", "email")}),
        (_("دسترسی‌ها"), {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_("تاریخ‌ها"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("mobile_number", "email", "first_name", "last_name",
                       "usable_password", "password1", "password2"),
        }),
    )

    def get_search_results(self, request, queryset, search_term):
        # Numbers are stored as +98912..., so "0912" or "۰۹۱۲" must be translated to match
        queryset, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        term = search_term.translate(DIGIT_MAP).strip()
        if term.isdigit() and term.startswith("0"):
            queryset |= self.model.objects.filter(mobile_number__startswith=f"+98{term[1:]}")
        return queryset, may_have_duplicates