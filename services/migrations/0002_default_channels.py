from django.db import migrations

# Placeholders: site admins replace the values in the admin panel ("راه‌های ارتباطی").
CHANNELS = [
    {"kind": "telegram", "label": "پشتیبانی تلگرام", "value": "@mahay_support", "order": 1},
    {"kind": "instagram", "label": "اینستاگرام MAHAY", "value": "mahay", "order": 2},
    {"kind": "eitaa", "label": "ایتا", "value": "@mahay_support", "order": 3},
    {"kind": "rubika", "label": "روبیکا", "value": "@mahay_support", "order": 4},
    {"kind": "phone", "label": "تماس تلفنی", "value": "09120000000", "order": 5},
]


def create_channels(apps, schema_editor):
    ContactChannel = apps.get_model("services", "ContactChannel")
    if ContactChannel.objects.exists():
        return
    for values in CHANNELS:
        ContactChannel.objects.create(is_active=False, **values)  # off until the real ids are filled in


def remove_channels(apps, schema_editor):
    ContactChannel = apps.get_model("services", "ContactChannel")
    ContactChannel.objects.filter(value__in=[values["value"] for values in CHANNELS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("services", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_channels, remove_channels),
    ]