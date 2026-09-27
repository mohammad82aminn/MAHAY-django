import django.db.models.deletion
from django.db import migrations, models


def split_groups(apps, schema_editor):
    """
    Until now a domain had one group, «مدیران حوزه X», and everyone in it had the same say. From
    here its members are the domain's experts (the group is renamed «کارشناسان حوزه X») and a new,
    empty «مدیران حوزه X» waits for a site admin to name the managers. Until someone is put in it
    the domain counts as having no manager, so its work goes straight to the site admins as before
    and nothing stops.

    The new group starts with the same permissions as the old one: whatever a site admin has
    granted that domain is kept, not reset.
    """
    Domain = apps.get_model("domains", "Domain")
    Group = apps.get_model("auth", "Group")
    for domain in Domain.objects.select_related("experts_group"):
        experts = domain.experts_group
        experts.name = f"کارشناسان حوزه {domain.name}"
        experts.save(update_fields=["name"])
        managers = Group.objects.create(name=f"مدیران حوزه {domain.name}")
        managers.permissions.set(experts.permissions.all())
        domain.managers_group = managers
        domain.save(update_fields=["managers_group"])


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("domains", "0002_domain_consulting_rate"),
    ]

    operations = [
        migrations.RenameField("domain", "group", "experts_group"),
        migrations.AlterField(
            model_name="domain",
            name="experts_group",
            field=models.OneToOneField(
                editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="experts_domain",
                to="auth.group", verbose_name="گروه کارشناسان",
            ),
        ),
        migrations.AddField(
            model_name="domain",
            name="managers_group",
            field=models.OneToOneField(
                editable=False, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="managers_domain", to="auth.group", verbose_name="گروه مدیران",
            ),
        ),
        migrations.RunPython(split_groups, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="domain",
            name="managers_group",
            field=models.OneToOneField(
                editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="managers_domain",
                to="auth.group", verbose_name="گروه مدیران",
            ),
        ),
    ]
