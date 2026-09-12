from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


class Page(models.Model):
    """
    A simple text page edited by site admins: "about us", "terms", "privacy", ...
    Needed for the payment gateway and the Iranian e-trust badge (اینماد).
    """

    title = models.CharField(_("عنوان"), max_length=200)
    slug = models.SlugField(
        _("نامک (انگلیسی)"), max_length=100, unique=True,
        help_text=_("بخش انگلیسی آدرس صفحه، مثلاً about یا terms"),
    )
    body = models.TextField(_("متن صفحه"), help_text=_("هر خط خالی یک پاراگراف جدید می‌سازد."))
    is_published = models.BooleanField(_("منتشر شده"), default=True)
    show_in_footer = models.BooleanField(_("نمایش در فوتر"), default=True)
    order = models.PositiveSmallIntegerField(_("ترتیب در فوتر"), default=0)
    updated_at = models.DateTimeField(_("آخرین تغییر"), auto_now=True)

    class Meta:
        verbose_name = _("صفحه")
        verbose_name_plural = _("صفحه‌ها")
        ordering = ("order", "title")

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("pages:detail", args=[self.slug])


class ContactMessage(models.Model):
    """A message sent from the contact form."""

    name = models.CharField(_("نام"), max_length=150)
    mobile_number = models.CharField(_("شماره تماس"), max_length=20, blank=True)
    email = models.EmailField(_("ایمیل"), blank=True)
    subject = models.CharField(_("موضوع"), max_length=200)
    body = models.TextField(_("پیام"))
    created_at = models.DateTimeField(_("زمان ارسال"), auto_now_add=True)
    is_handled = models.BooleanField(_("بررسی شد"), default=False)

    class Meta:
        verbose_name = _("پیام تماس")
        verbose_name_plural = _("پیام‌های تماس")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.subject} — {self.name}"