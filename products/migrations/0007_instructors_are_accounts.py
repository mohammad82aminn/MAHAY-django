from django.conf import settings
from django.db import migrations, models


def link_named_instructors(apps, schema_editor):
    """
    The instructor used to be typed as text. Each name that matches exactly one staff member's full
    name is linked to that account; a name that matches nobody, or more than one person, is left
    for a site admin to pick by hand, and listed so it isn't forgotten.
    """
    Product = apps.get_model("products", "Product")
    User = apps.get_model(settings.AUTH_USER_MODEL.split(".")[0], settings.AUTH_USER_MODEL.split(".")[1])
    staff = list(User.objects.filter(is_staff=True))

    def full_name(user):
        return " ".join(f"{user.first_name} {user.last_name}".split())

    for product in Product.objects.exclude(instructor=""):
        for name in (part.strip() for part in product.instructor.replace(",", "،").split("،")):
            matches = [user for user in staff if full_name(user) == " ".join(name.split())]
            if len(matches) == 1:
                product.instructors.add(matches[0])


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0006_productimage_created_by"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="instructors",
            field=models.ManyToManyField(
                blank=True, limit_choices_to={"is_active": True, "is_staff": True}, related_name="taught_products",
                to=settings.AUTH_USER_MODEL, verbose_name="مدرسان",
                help_text="روی کارت و صفحه‌ی محصول نمایش داده می‌شوند. اگر چند نفرند، سهم مدرس بینشان مساوی تقسیم می‌شود.",
            ),
        ),
        migrations.RunPython(link_named_instructors, migrations.RunPython.noop),
        migrations.RemoveField(model_name="product", name="instructor"),
    ]
