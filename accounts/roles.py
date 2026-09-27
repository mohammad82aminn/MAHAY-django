"""
Access rules of MAHAY (group based — permissions are never given to individual users).

- Site admins: members of "مدیران کل" or "مدیران فنی" -> every permission of the site (kept automatically).
  The two groups have the same access; only the name differs (site management vs. technical duties).
- Domain managers and experts: members of a domain's «مدیران حوزه» / «کارشناسان حوزه» group
  (both created automatically for each domain; see domains.access).
  WHAT they may do is chosen by site admins in the admin panel (group permissions);
  WHERE they may do it (only their own domain) and what a manager may do beyond an expert
  are enforced in code.
- Who is in the full-access groups is the system owner's (superuser's) decision alone.
- Normal users: no group.

Anyone who is in at least one group can log into the admin panel (is_staff is set automatically).
"""
from django.contrib.auth.models import Group, Permission

SITE_ADMINS_GROUP = "مدیران کل"

TECH_ADMINS_GROUP = "مدیران فنی"
FULL_ACCESS_GROUPS = (SITE_ADMINS_GROUP, TECH_ADMINS_GROUP)
# Staff (ستاد): sees every toman that comes in and records payouts, and nothing else of the site
FINANCE_GROUP = "مدیران مالی"
# Who is in these is the system owner's decision alone (see accounts.admin.UserAdmin)
OWNER_ONLY_GROUPS = (*FULL_ACCESS_GROUPS, FINANCE_GROUP)
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


def role_label(user):
    """
    What a person's role is called wherever it is shown: the user list, the recipient picker
    in the کارپوشه, the admin header. One wording for one idea, so the same person is never
    described two different ways in two places.
    """
    names = [group.name for group in user.groups.all()]
    if user.is_superuser:
        names.insert(0, "مالک سیستم")
    return "، ".join(names) or "کاربر عادی"


def is_site_admin(user):
    """Superuser or member of a full-access group (works for any user object, even anonymous)."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.groups.filter(name__in=FULL_ACCESS_GROUPS).exists()


def is_system_group(group):
    """Groups managed by the system: the full-access groups and every domain's two groups."""
    from domains.access import is_domain_group

    return group.name in OWNER_ONLY_GROUPS or is_domain_group(group)


def ensure_site_admins_group():
    """
    Create the system's staff groups if missing and keep their permissions whole: every permission
    of the site for the full-access groups, the finance app's for the finance managers.
    """
    groups = []
    for name in FULL_ACCESS_GROUPS:
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set(Permission.objects.all())
        groups.append(group)
    finance, _ = Group.objects.get_or_create(name=FINANCE_GROUP)
    finance.permissions.set(Permission.objects.filter(content_type__app_label="finance"))
    return groups[0]


def is_finance_manager(user):
    """In the finance managers group. Site admins see the money too, through is_site_admin."""
    return bool(user.is_authenticated and user.groups.filter(name=FINANCE_GROUP).exists())


def can_see_finance(user):
    return is_site_admin(user) or is_finance_manager(user)


def sync_staff_status(user_ids):
    """is_staff = superuser OR member of any group. Called whenever group memberships change."""
    from .models import User

    for user in User.objects.filter(pk__in=user_ids):
        should_be_staff = user.is_superuser or user.groups.exists()
        if user.is_staff != should_be_staff:
            User.objects.filter(pk=user.pk).update(is_staff=should_be_staff)