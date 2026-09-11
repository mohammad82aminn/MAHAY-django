from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

from approvals.admin_base import ApprovalModelAdmin

from .models import Product, ProductImage


class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = "__all__"
        widgets = {
            "slug": forms.TextInput(attrs={"dir": "ltr"}),
            "intro_video_url": forms.URLInput(attrs={"dir": "ltr"}),
        }

    def clean(self):
        super().clean()
        data = self.cleaned_data
        instance = self.instance

        primary, related = data.get("primary_domain"), data.get("related_domains")
        if primary and related and primary in related:
            self.add_error("related_domains", _("حوزه‌ی اصلی را در حوزه‌های مرتبط انتخاب نکنید."))

        if instance.pk and instance in (data.get("related_products") or []):
            self.add_error("related_products", _("محصول نمی‌تواند با خودش مرتبط باشد."))

        # "Includes" is one level only: a bundle can't include another bundle or itself
        included = data.get("included_products") or []
        if instance.pk and instance in included:
            self.add_error("included_products", _("محصول نمی‌تواند شامل خودش باشد."))
        elif any(product.included_products.exists() for product in included):
            self.add_error("included_products", _("محصولی که خودش شامل محصولات دیگر است را نمی‌توان اضافه کرد."))
        elif included and instance.pk and instance.included_in.exists():
            self.add_error("included_products", _("این محصول داخل محصول دیگری است و نمی‌تواند شامل محصول باشد."))
        return data


@admin.register(Product)
class ProductAdmin(ApprovalModelAdmin):
    form = ProductAdminForm
    list_display = ("title", "product_type", "primary_domain", "price_display", "state")
    list_filter = ("product_type", "primary_domain", "is_published", "is_archived")
    search_fields = ("title", "slug")
    filter_horizontal = ("related_domains", "related_products", "included_products")
    readonly_fields = ("cover_preview", "gallery", "content_outline", "created_by", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("product_type", "title", "slug", "summary", "description")}),
        (_("تصاویر و ویدیوی معرفی"), {"fields": ("cover", "cover_preview", "gallery", "intro_video_url")}),
        (_("حوزه"), {"fields": ("primary_domain", "related_domains")}),
        (_("قیمت"), {"fields": ("price", "sale_price")}),
        (_("محصولات مرتبط و بسته‌ها"), {"fields": ("related_products", "included_products")}),
        (_("محتوا"), {"fields": ("content_outline",)}),
        (_("وضعیت"), {"fields": ("is_published", "is_archived", "created_by", "created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("primary_domain")

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change=change, **kwargs)
        if obj is not None:
            # A product can't be related to / include itself, so don't even offer it
            for name in ("related_products", "included_products"):
                field = form.base_fields.get(name)
                if isinstance(field, forms.ModelMultipleChoiceField) and field.queryset is not None:
                    field.queryset = field.queryset.exclude(pk=obj.pk)
        return form

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        # A manager may only bundle products of their own domains (never give away another domain's product)
        if db_field.name == "included_products" and not self.is_reviewer(request):
            kwargs["queryset"] = Product.objects.filter(primary_domain__group__user=request.user)
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    @admin.display(description=_("قیمت"))
    def price_display(self, obj):
        if obj.is_free:
            return "رایگان"
        if obj.sale_price is not None:
            return f"{obj.sale_price:,} تومان ({obj.discount_percent}٪ تخفیف)"
        return f"{obj.price:,} تومان"

    @admin.display(description=_("پیش‌نمایش کاور"))
    def cover_preview(self, obj):
        if not obj.cover:
            return "—"
        return format_html('<img src="{}" style="max-width:320px;border-radius:8px">', obj.cover.url)

    @admin.display(description=_("گالری تصاویر"))
    def gallery(self, obj):
        if not obj.pk:
            return "بعد از ذخیره‌ی محصول، تصاویر گالری را اضافه کنید."
        images = format_html_join(
            "", '<img src="{}" title="{}" style="height:64px;border-radius:6px;margin:2px">',
            ((image.image.url, image.caption) for image in obj.images.all()),
        )
        add_url = f"{reverse('admin:products_productimage_add')}?product={obj.pk}"
        list_url = f"{reverse('admin:products_productimage_changelist')}?product__id__exact={obj.pk}"
        return format_html('<div>{}</div><p><a href="{}">+ افزودن تصویر</a> &nbsp;|&nbsp; <a href="{}">مدیریت تصاویر</a></p>',
                           images or "", add_url, list_url)

    @admin.display(description=_("بخش‌ها و درس‌ها"))
    def content_outline(self, obj):
        if not obj.pk:
            return "بعد از ذخیره‌ی محصول، بخش‌ها و درس‌ها را اضافه کنید."
        sections = obj.sections.prefetch_related("lessons")
        rows = format_html_join(
            "", '<li><a href="{}">{}</a> — {} درس</li>',
            (
                (reverse("admin:content_section_change", args=[section.pk]), section.title, section.lessons.count())
                for section in sections
            ),
        )
        add_url = f"{reverse('admin:content_section_add')}?product={obj.pk}"
        lessons_url = f"{reverse('admin:content_lesson_changelist')}?section__product__id__exact={obj.pk}"
        return format_html(
            '<ul style="margin:0">{}</ul><p><a href="{}">+ افزودن بخش</a> &nbsp;|&nbsp; <a href="{}">همه‌ی درس‌ها</a></p>',
            rows or "", add_url, lessons_url,
        )


@admin.register(ProductImage)
class ProductImageAdmin(ApprovalModelAdmin):
    domain_field = "product__primary_domain"
    list_display = ("thumbnail", "product", "caption", "order", "state")
    list_filter = ("product__primary_domain", "product")
    search_fields = ("caption", "product__title")
    fields = ("product", "image", "thumbnail", "caption", "order", "is_published", "is_archived")
    readonly_fields = ("thumbnail",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("product")

    @admin.display(description=_("پیش‌نمایش"))
    def thumbnail(self, obj):
        if not obj.pk or not obj.image:
            return "—"
        return format_html('<img src="{}" style="height:64px;border-radius:6px">', obj.image.url)