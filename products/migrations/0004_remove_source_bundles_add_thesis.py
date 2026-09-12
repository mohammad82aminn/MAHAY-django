import content.storage
from django.db import migrations, models


def source_to_project(apps, schema_editor):
    """The "source code" product type is removed: existing ones become projects."""
    Product = apps.get_model("products", "Product")
    Product.objects.filter(product_type="source").update(product_type="project")


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0003_alter_product_cover_productimage"),
    ]

    operations = [
        migrations.RunPython(source_to_project, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="product",
            name="included_products",
        ),
        migrations.AlterField(
            model_name="product",
            name="product_type",
            field=models.CharField(
                choices=[("course", "دوره آموزشی"), ("project", "پروژه")],
                max_length=10,
                verbose_name="نوع محصول",
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="thesis",
            field=models.FileField(
                blank=True,
                help_text="فقط برای پروژه‌ها. فقط خریداران می‌توانند دانلود کنند.",
                storage=content.storage.protected_storage,
                upload_to="thesis/%Y/%m/",
                verbose_name="پایان‌نامه",
            ),
        ),
    ]