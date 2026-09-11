from django.contrib.auth.models import Group, Permission

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