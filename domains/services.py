from django.contrib.auth.models import Group, Permission
from django.db.models import Q

# Default permissions of a NEW domain group, as "app_label.codename".
# After creation, site admins can change each domain group's permissions in the admin panel ("گروه‌ها").
DEFAULT_DOMAIN_MANAGER_PERMISSIONS = [
    "domains.view_domain",
    "products.view_product",
    "products.add_product",
    "products.change_product",
    "products.delete_product",
    "products.view_productimage", "products.add_productimage", "products.change_productimage",
    "products.delete_productimage",
    "content.view_section", "content.add_section", "content.change_section", "content.delete_section",
    "content.view_lesson", "content.add_lesson", "content.change_lesson", "content.delete_lesson",
    "content.view_attachment", "content.add_attachment", "content.change_attachment", "content.delete_attachment",
    "content.view_productfile", "content.add_productfile", "content.change_productfile", "content.delete_productfile",
    "approvals.view_changerequest",
    # service requests: managers see the files referred to them and report on their own referral
    "services.view_servicerequest",
    "services.view_referral", "services.change_referral",
    "services.view_requestmessage", "services.add_requestmessage",
    "services.view_requestevent",  # the file's own history, so a manager can see what happened
]


def default_permissions():
    lookup = Q()
    for item in DEFAULT_DOMAIN_MANAGER_PERMISSIONS:
        app_label, codename = item.split(".")
        lookup |= Q(content_type__app_label=app_label, codename=codename)
    return Permission.objects.filter(lookup)


def apply_default_permissions(group):
    """
    Give a group everything the domain manager role needs, and report what it holds beyond that.

    Only ever adds. Permissions granted by hand are somebody's decision and are left alone —
    they are named in the return value instead, for a person to judge.
    """
    wanted = set(default_permissions())
    held = set(group.permissions.all())
    missing = wanted - held
    group.permissions.add(*missing)
    return missing, held - wanted


def create_domain_group(name):
    group = Group.objects.create(name=name)
    group.permissions.add(*default_permissions())
    return group