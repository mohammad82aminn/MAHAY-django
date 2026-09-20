from django.contrib.auth.models import Group
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _


class Domain(models.Model):
    """
    A field of work, e.g. AI, FPGA, Network.
    Each domain gets its own group automatically; adding a user to that group makes them a manager of it.
    """

    name = models.CharField(_("نام حوزه"), max_length=100, unique=True)
    slug = models.SlugField(
        _("نامک (انگلیسی)"),
        max_length=100,
        unique=True,
        help_text=_("بخش انگلیسی آدرس صفحه، مثلاً fpga یا ai"),
    )
    description = models.TextField(_("توضیحات"), blank=True)
    is_active = models.BooleanField(_("فعال"), default=True, help_text=_("حوزه‌ی غیرفعال در سایت نمایش داده نمی‌شود."))
    consulting_rate = models.PositiveIntegerField(
        _("نرخ مشاوره‌ی هر ۱۵ دقیقه (تومان)"), null=True, blank=True,
        help_text=_("خالی یعنی نرخ پیش‌فرض سایت."),
    )
    order = models.PositiveSmallIntegerField(_("ترتیب نمایش"), default=0)
    group = models.OneToOneField(
        Group,
        verbose_name=_("گروه مدیران"),
        on_delete=models.PROTECT,  # the group can't be deleted while its domain exists
        related_name="domain",
        editable=False,
    )
    created_at = models.DateTimeField(_("تاریخ ایجاد"), auto_now_add=True)

    class Meta:
        verbose_name = _("حوزه")
        verbose_name_plural = _("حوزه‌ها")
        ordering = ("order", "name")

    def __str__(self):
        return self.name

    @staticmethod
    def group_name_for(name):
        return f"مدیران حوزه {name}"

    def save(self, *args, **kwargs):
        # Create the managers group on first save, keep its name in sync on rename
        from .services import create_domain_group

        with transaction.atomic():  # if saving the domain fails, the new group is rolled back too
            if self._state.adding:
                self.group = create_domain_group(self.group_name_for(self.name))
            elif self.group.name != self.group_name_for(self.name):
                self.group.name = self.group_name_for(self.name)
                self.group.save(update_fields=["name"])
            super().save(*args, **kwargs)