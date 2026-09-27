"""
Access rules of MAHAY (group based — permissions are never given to individual users).

- Site admins: members of "مدیران کل" -> every permission of the site (kept automatically). They
  alone make the decisions: approving, referring, pricing, payments, roles.
- Staff (ستاد), each with a group of its own and nothing beyond it:
  - "مدیران فنی": support. Sees the whole panel read-only to find what is wrong (sees_everything),
    edits only the site's own pages and contact channels, and runs «درخواست‌های فنی». Never the
    money, the office reports, anyone's CV or anyone's کارپوشه.
  - "مدیران مالی": the finance pages (see can_see_finance).
  - "مدیران اداری": watches the staff — directory, activity, performance — and reports to the site
    admins; decides nothing.
- Domain managers and experts: members of a domain's «مدیران حوزه» / «کارشناسان حوزه» group
  (both created automatically for each domain; see domains.access).
  WHAT they may do is chosen by site admins in the admin panel (group permissions);
  WHERE they may do it (only their own domain) and what a manager may do beyond an expert
  are enforced in code.
- Who is in the full-access and staff groups is the system owner's (superuser's) decision alone.
- Normal users: no group.

Anyone who is in at least one group can log into the admin panel (is_staff is set automatically).
"""
from django.contrib.auth.models import Group, Permission

SITE_ADMINS_GROUP = "مدیران کل"

FULL_ACCESS_GROUPS = (SITE_ADMINS_GROUP,)
# Staff (ستاد)
TECH_ADMINS_GROUP = "مدیران فنی"
FINANCE_GROUP = "مدیران مالی"
OFFICE_GROUP = "مدیران اداری"
STAFF_GROUPS = (TECH_ADMINS_GROUP, FINANCE_GROUP, OFFICE_GROUP)
# Who is in these is the system owner's decision alone (see accounts.admin.UserAdmin)
OWNER_ONLY_GROUPS = (*FULL_ACCESS_GROUPS, *STAFF_GROUPS)

# What the technical admins may not even look at: the money, the office's reports, the inboxes and
# applicants' CVs are nobody's business in fixing the site
TECH_HIDDEN_APPS = ("finance", "office", "inbox", "collaboration")
# ...and within the other apps, the payments and orders (money too) and the marketing report.
# Purchases stay visible: "I paid but can't open the course" is exactly a support question.
TECH_HIDDEN_MODELS = (
    ("services", "requestpayment"), ("services", "heardfromreport"), ("commerce", "order"), ("commerce", "orderitem"),
)
# ...and the only things they change: the site's own pages and how to reach us
TECH_EDITS = (("pages", "page"), ("services", "contactchannel"))
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
    Create the system's groups if missing and keep their permissions whole (runs after every
    migrate, so new models are covered): everything for the site admins; for the technical admins,
    viewing all but TECH_HIDDEN_APPS and changing TECH_EDITS; the finance app for the finance
    managers; the office app for the office managers.
    """
    from django.db.models import Q

    site_admins, _ = Group.objects.get_or_create(name=SITE_ADMINS_GROUP)
    site_admins.permissions.set(Permission.objects.all())

    edits = Q()
    for app_label, model in TECH_EDITS:
        edits |= Q(content_type__app_label=app_label, **({"content_type__model": model} if model else {}))
    hidden = Q(content_type__app_label__in=TECH_HIDDEN_APPS)
    for app_label, model in TECH_HIDDEN_MODELS:
        hidden |= Q(content_type__app_label=app_label, content_type__model=model)
    tech, _ = Group.objects.get_or_create(name=TECH_ADMINS_GROUP)
    tech.permissions.set(Permission.objects.exclude(hidden).filter(Q(codename__startswith="view_") | edits))

    for name, app_label in ((FINANCE_GROUP, "finance"), (OFFICE_GROUP, "office")):
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set(Permission.objects.filter(content_type__app_label=app_label))
    return site_admins


def in_group(user, name):
    return bool(user.is_authenticated and user.groups.filter(name=name).exists())


def is_tech_admin(user):
    return in_group(user, TECH_ADMINS_GROUP)


def is_office_manager(user):
    return in_group(user, OFFICE_GROUP)


def sees_everything(user):
    """
    Who is shown every domain's content and every request, not just their own: the site admins,
    and the technical admins to find what is wrong. Seeing is not deciding — that stays is_site_admin.
    """
    return is_site_admin(user) or is_tech_admin(user)


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