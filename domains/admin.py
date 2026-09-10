from django.contrib import admin
from django.db.models import Count

from accounts.roles import is_site_admin

from .models import Domain


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "order", "manager_count")
    list_editable = ("is_active", "order")
    search_fields = ("name", "slug")
    readonly_fields = ("group", "managers", "created_at")
    fields = ("name", "slug", "description", "is_active", "order", "group", "managers", "created_at")

    def get_queryset(self, request):
        # Domain managers only see their own domains; site admins see all
        queryset = super().get_queryset(request).select_related("group").annotate(_manager_count=Count("group__user"))
        if is_site_admin(request.user):
            return queryset
        return queryset.filter(group__user=request.user)

    @admin.display(description="تعداد مدیران", ordering="_manager_count")
    def manager_count(self, obj):
        return obj._manager_count

    @admin.display(description="مدیران")
    def managers(self, obj):
        if not obj.pk:
            return "بعد از ذخیره، افراد را از بخش کاربران به گروه این حوزه اضافه کنید."
        return "، ".join(str(user) for user in obj.group.user_set.all()) or "هنوز مدیری ندارد"