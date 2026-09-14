"""
Access rules of MAHAY (group based — permissions are never given to individual users).

- Site admins: members of "مدیران کل" or "مدیران فنی" -> every permission of the site (kept automatically).
  The two groups have the same access; only the name differs (site management vs. technical duties).
- Domain managers: members of a domain's group (created automatically for each domain).
  WHAT they may do is chosen by site admins in the admin panel (group permissions);
  WHERE they may do it (only their own domain) is enforced in code.
- Normal users: no group.

Anyone who is in at least one group can log into the admin panel (is_staff is set automatically).
"""
from django.contrib.auth.models import Group, Permission

SITE_ADMINS_GROUP = "مدیران کل"

TECH_ADMINS_GROUP = "مدیران فنی"
FULL_ACCESS_GROUPS = (SITE_ADMINS_GROUP, TECH_ADMINS_GROUP)
# Apps whose permissions may be given to domain groups (content only; never users or groups).
# When courses and projects are built, their app labels are added here.
DOMAIN_MANAGER_APPS = ("domains", "products", "content", "approvals", "services")

# Never offered to domain groups:
# - domains: creating, editing or deleting a domain is the site admins' job
# - approvals: managers may only VIEW requests; deciding is the site admins' job
DOMAIN_MANAGER_FORBIDDEN = (
    "add_domain", "change_domain", "delete_domain",
    "add_changerequest", "change_changerequest", "delete_changerequest",
    # service requests: managers work on their referral, not on the request itself
    "add_servicerequest", "change_servicerequest", "delete_servicerequest",
    "add_requestpayment", "change_requestpayment", "delete_requestpayment",
    "add_requestevent", "change_requestevent", "delete_requestevent",
    "add_contactchannel", "change_contactchannel", "delete_contactchannel",
    "add_referral", "delete_referral",  # the site admin decides who a request goes to
)


def is_site_admin(user):
    """Superuser or member of a full-access group (works for any user object, even anonymous)."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.groups.filter(name__in=FULL_ACCESS_GROUPS).exists()


def is_system_group(group):
    """Groups managed by the system: the full-access groups and every domain group."""
    return group.name in FULL_ACCESS_GROUPS or hasattr(group, "domain")


def ensure_site_admins_group():
    """Create the full-access groups (if missing) and give them every permission of the site."""
    groups = []
    for name in FULL_ACCESS_GROUPS:
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set(Permission.objects.all())
        groups.append(group)
    return groups[0]


def sync_staff_status(user_ids):
    """is_staff = superuser OR member of any group. Called whenever group memberships change."""
    from .models import User

    for user in User.objects.filter(pk__in=user_ids):
        should_be_staff = user.is_superuser or user.groups.exists()
        if user.is_staff != should_be_staff:
            User.objects.filter(pk=user.pk).update(is_staff=should_be_staff)