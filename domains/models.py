from django.contrib.auth.models import Group
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _


class Domain(models.Model):
    """
    A field of work, e.g. AI, FPGA, Network.

    Each domain gets two groups automatically, and belonging to one is the only way to a role in it
    (access is never given to a person):
    - «مدیران حوزه X»: review their experts' work before it reaches the site admins, pick who
      does each project order, and alone edit or remove what is already published. One or more.
    - «کارشناسان حوزه X»: make content and do the project orders handed to them.
    See domains.access for the questions code asks about them.
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
    # The groups can't be deleted while their domain exists
    managers_group = models.OneToOneField(
        Group, verbose_name=_("گروه مدیران"), on_delete=models.PROTECT, related_name="managers_domain",
        editable=False,
    )
    experts_group = models.OneToOneField(
        Group, verbose_name=_("گروه کارشناسان"), on_delete=models.PROTECT, related_name="experts_domain",
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
    def managers_group_name(name):
        return f"مدیران حوزه {name}"

    @staticmethod
    def experts_group_name(name):
        return f"کارشناسان حوزه {name}"

    @property
    def groups(self):
        return (self.managers_group, self.experts_group)

    def save(self, *args, **kwargs):
        # Create the two groups on first save, keep their names in sync on rename
        from .services import create_domain_group

        with transaction.atomic():  # if saving the domain fails, the new groups are rolled back too
            if self._state.adding:
                self.managers_group = create_domain_group(self.managers_group_name(self.name))
                self.experts_group = create_domain_group(self.experts_group_name(self.name))
            else:
                for group, wanted in ((self.managers_group, self.managers_group_name(self.name)),
                                      (self.experts_group, self.experts_group_name(self.name))):
                    if group.name != wanted:
                        group.name = wanted
                        group.save(update_fields=["name"])
            super().save(*args, **kwargs)
