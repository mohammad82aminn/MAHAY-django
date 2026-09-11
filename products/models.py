from typing import ClassVar
from django.db import models
from django.urls import reverse

from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from content.models import PublishState
from content.validators import validate_aparat_url


class ProductQuerySet(models.QuerySet):
    def visible(self):
        """Products shown in the store: approved, not removed, and their domain is active."""
        return self.filter(is_published=True, is_archived=False, primary_domain__is_active=True)

class ProductManager(models.Manager["Product"]):
    def get_queryset(self):
        return ProductQuerySet(self.model, using=self._db)

    def visible(self):
        return self.get_queryset().visible()


class Product(models.Model):
    """Base of everything that is sold: courses and projects."""

    class Type(models.TextChoices):
        COURSE = "course", _("دوره آموزشی")
        PROJECT = "project", _("پروژه")
        SOURCE = "source", _("سورس‌کد و فایل")

    product_type = models.CharField(_("نوع محصول"), max_length=10, choices=Type.choices)
    title = models.CharField(_("عنوان"), max_length=200)
    slug = models.SlugField(
        _("نامک (انگلیسی)"), max_length=200, unique=True,
        help_text=_("بخش انگلیسی آدرس صفحه، مثلاً fpga-basics"),
    )
    summary = models.CharField(_("خلاصه"), max_length=300, blank=True, help_text=_("یک یا دو جمله برای کارت محصول"))
    description = models.TextField(_("توضیحات کامل"), blank=True)
    cover = models.ImageField(
        _("تصویر کاور"), upload_to="products/covers/", blank=True,
        help_text=_("در لیست محصولات نمایش داده می‌شود و برای انتشار لازم است. اندازه‌ی پیشنهادی: ۱۲۸۰×۷۲۰ (افقی ۱۶:۹)."),
    )
    intro_video_url = models.URLField(
        _("ویدیوی معرفی (لینک آپارات)"), blank=True, validators=[validate_aparat_url],
        help_text=_("برای همه نمایش داده می‌شود؛ مثلاً مدرس توضیح می‌دهد در دوره چه چیزی آموزش داده می‌شود."),
    )

    primary_domain = models.ForeignKey(
        "domains.Domain", on_delete=models.PROTECT, related_name="products", verbose_name=_("حوزه اصلی"),
        help_text=_("مدیران این حوزه مسئول محصول هستند."),
    )
    related_domains = models.ManyToManyField(
        "domains.Domain", blank=True, related_name="related_products", verbose_name=_("حوزه‌های مرتبط"),
        help_text=_("محصول در این حوزه‌ها هم نمایش داده می‌شود."),
    )

    related_products = models.ManyToManyField(
        "self", blank=True, verbose_name=_("محصولات مرتبط"),
        help_text=_("در صفحه‌ی محصول لینکشان نمایش داده می‌شود؛ مثلاً دوره‌ی آموزشی همین پروژه. (دوطرفه)"),
    )
    included_products = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="included_in", verbose_name=_("شامل محصولات"),
        help_text=_("خریدار این محصول، این‌ها را هم دارد؛ مثلاً پروژه شامل «سورس‌کد پروژه» می‌شود."),
    )

    price = models.PositiveIntegerField(_("قیمت (تومان)"), default=0, help_text=_("صفر یعنی رایگان"))
    sale_price = models.PositiveIntegerField(
        _("قیمت با تخفیف (تومان)"), null=True, blank=True, help_text=_("خالی یعنی بدون تخفیف"),
    )

    is_published = models.BooleanField(_("منتشر شده"), default=False)
    is_archived = models.BooleanField(
        _("حذف از فروشگاه"), default=False, help_text=_("در فروشگاه نمایش داده نمی‌شود، ولی خریداران دسترسی دارند."),
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False,
        related_name="created_products", verbose_name=_("سازنده"),
    )
    created_at = models.DateTimeField(_("تاریخ ایجاد"), auto_now_add=True)
    updated_at = models.DateTimeField(_("آخرین تغییر"), auto_now=True)

    change_requests = GenericRelation("approvals.ChangeRequest")  # deleted together with the product

    objects: ClassVar[ProductManager] = ProductManager()

    class Meta:
        verbose_name = _("محصول")
        verbose_name_plural = _("محصولات")
        ordering = ("-created_at",)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("products:detail", args=[self.slug])

    def approval_children(self):
        from content.models import Section

        return [*Section.objects.filter(product=self), *ProductImage.objects.filter(product=self)]

    def clean(self):
        if self.is_published and not self.cover:
            raise ValidationError({"cover": _("برای انتشار محصول، تصویر کاور لازم است.")})
        if self.sale_price is not None:
            if self.price == 0:
                raise ValidationError({"sale_price": _("محصول رایگان تخفیف ندارد.")})
            if self.sale_price >= self.price:
                raise ValidationError({"sale_price": _("قیمت با تخفیف باید کمتر از قیمت اصلی باشد.")})

    @property
    def final_price(self):
        return self.sale_price if self.sale_price is not None else self.price

    @property
    def is_free(self):
        return self.final_price == 0

    @property
    def discount_percent(self):
        if self.sale_price is None or not self.price:
            return 0
        return round((self.price - self.sale_price) * 100 / self.price)


class ProductImage(PublishState):
    """Gallery image shown on the product page (e.g. photos of a built project). Public, like the cover."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images", verbose_name=_("محصول"))
    image = models.ImageField(_("تصویر"), upload_to="products/gallery/%Y/%m/")
    caption = models.CharField(_("توضیح کوتاه"), max_length=200, blank=True)

    class Meta(PublishState.Meta):
        verbose_name = _("تصویر گالری")
        verbose_name_plural = _("گالری تصاویر")

    def __str__(self):
        return self.caption or f"تصویر {self.pk} — {self.product}"