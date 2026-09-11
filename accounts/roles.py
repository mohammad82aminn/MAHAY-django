"""
Access rules of MAHAY (group based — permissions are never given to individual users).

- Site admins: members of the "مدیران کل" group -> every permission of the site (kept automatically).
- Domain managers: members of a domain's group (created automatically for each domain).
  WHAT they may do is chosen by site admins in the admin panel (group permissions);
  WHERE they may do it (only their own domain) is enforced in code.
- Normal users: no group.

Anyone who is in at least one group can log into the admin panel (is_staff is set automatically).
"""
from django.contrib.auth.models import Group, Permission

SITE_ADMINS_GROUP = "مدیران کل"

# Apps whose permissions may be given to domain groups (content only; never users or groups).
# When courses and projects are built, their app labels are added here.
DOMAIN_MANAGER_APPS = ("domains", "products", "approvals")

# Never offered to domain groups:
# - domains: creating, editing or deleting a domain is the site admins' job
# - approvals: managers may only VIEW requests; deciding is the site admins' job
DOMAIN_MANAGER_FORBIDDEN = (
    "add_domain", "change_domain", "delete_domain",
    "add_changerequest", "change_changerequest", "delete_changerequest",
)


def is_site_admin(user):
    """Superuser or member of the site admins group (works for any user object, even anonymous)."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.groups.filter(name=SITE_ADMINS_GROUP).exists()


def is_system_group(group):
    """Groups managed by the system: the site admins group and every domain group."""
    return group.name == SITE_ADMINS_GROUP or hasattr(group, "domain")


def ensure_site_admins_group():
    """Create the site admins group (if missing) and give it every permission of the site."""
    group, _ = Group.objects.get_or_create(name=SITE_ADMINS_GROUP)
    group.permissions.set(Permission.objects.all())
    return group


def sync_staff_status(user_ids):
    """is_staff = superuser OR member of any group. Called whenever group memberships change."""
    from .models import User

    for user in User.objects.filter(pk__in=user_ids):
        should_be_staff = user.is_superuser or user.groups.exists()
        if user.is_staff != should_be_staff:
            User.objects.filter(pk=user.pk).update(is_staff=should_be_staff)