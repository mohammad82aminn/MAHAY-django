from django.contrib import admin
from django.db.models import Count

from accounts.roles import is_site_admin

from .access import member_domains
from .models import Domain


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "order", "consulting_rate", "manager_names", "expert_count")
    list_editable = ("is_active", "order", "consulting_rate")
    search_fields = ("name", "slug")
    readonly_fields = ("managers_group", "experts_group", "managers", "experts", "created_at")
    fields = ("name", "slug", "description", "is_active", "order", "consulting_rate",
              "managers_group", "managers", "experts_group", "experts", "created_at")

    def get_queryset(self, request):
        # Domain managers and experts only see their own domains; site admins see all
        queryset = (
            super().get_queryset(request)
            .select_related("managers_group", "experts_group")
            .prefetch_related("managers_group__user_set")
            .annotate(_expert_count=Count("experts_group__user", distinct=True))
        )
        if is_site_admin(request.user):
            return queryset
        return queryset.filter(pk__in=member_domains(request.user))

    @admin.display(description="مدیران")
    def manager_names(self, obj):
        return "، ".join(str(user) for user in obj.managers_group.user_set.all()) or "—"

    @admin.display(description="تعداد کارشناسان", ordering="_expert_count")
    def expert_count(self, obj):
        return obj._expert_count

    @admin.display(description="مدیران حوزه")
    def managers(self, obj):
        if not obj.pk:
            return "بعد از ذخیره، افراد را از بخش کاربران به گروه مدیران این حوزه اضافه کنید."
        names = "، ".join(str(user) for user in obj.managers_group.user_set.all())
        return names or "هنوز مدیری ندارد؛ تا تعیین مدیر، کارهای این حوزه مستقیم برای مدیر کل فرستاده می‌شود."

    @admin.display(description="کارشناسان حوزه")
    def experts(self, obj):
        if not obj.pk:
            return "بعد از ذخیره، افراد را از بخش کاربران به گروه کارشناسان این حوزه اضافه کنید."
        return "، ".join(str(user) for user in obj.experts_group.user_set.all()) or "هنوز کارشناسی ندارد"
