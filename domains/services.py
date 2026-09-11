from django.contrib.auth.models import Group, Permission

# Default permissions of a NEW domain group, as "app_label.codename".
# After creation, site admins can change each domain group's permissions in the admin panel ("گروه‌ها").
DEFAULT_DOMAIN_MANAGER_PERMISSIONS = [
    "domains.view_domain",
    "products.view_product",
    "products.add_product",
    "products.change_product",
    "products.delete_product",
    "approvals.view_changerequest",
]


def create_domain_group(name):
    group = Group.objects.create(name=name)
    for item in DEFAULT_DOMAIN_MANAGER_PERMISSIONS:
        app_label, codename = item.split(".")
        permission = Permission.objects.filter(content_type__app_label=app_label, codename=codename).first()
        if permission:
            group.permissions.add(permission)
    return group