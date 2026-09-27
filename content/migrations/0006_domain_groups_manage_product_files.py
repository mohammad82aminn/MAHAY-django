from django.contrib.auth.management import create_permissions
from django.db import migrations

CODENAMES = ("view_productfile", "add_productfile", "change_productfile", "delete_productfile")


def grant(apps, schema_editor):
    """
    Domain managers already look after the sections, lessons and files of their products; the
    whole-course files are the same job. New domains get these by default — existing ones here.
    Only adds, like the admin's «اعمال دسترسی‌های پیش‌فرض» action.
    """
    # Permissions are normally made after migrate; make them now. The historical app config lacks
    # the attribute create_permissions checks, so it is set for the call.
    app_config = apps.get_app_config("content")
    app_config.models_module = True
    create_permissions(app_config, verbosity=0, apps=apps)
    app_config.models_module = None
    Permission = apps.get_model("auth", "Permission")
    Domain = apps.get_model("domains", "Domain")
    permissions = list(Permission.objects.filter(content_type__app_label="content", codename__in=CODENAMES))
    for domain in Domain.objects.select_related("group"):
        domain.group.permissions.add(*permissions)


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0005_productfile"),
        ("domains", "__first__"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(grant, migrations.RunPython.noop),
    ]
