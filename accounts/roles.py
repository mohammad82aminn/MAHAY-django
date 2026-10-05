"""
Access rules of MAHAY (group based — permissions are never given to individual users).

- Site admins: members of "مدیران کل" -> every permission of the site (kept automatically). They
  alone make the decisions: approving, referring, pricing, payments, roles.
- Staff (ستاد), each with a group of its own. Each starts with the permissions of its job
  (staff_default_permissions); the site admins can change them in the panel afterwards, though
  never to a change of accounts, groups or permissions (STAFF_WRITE_FORBIDDEN_APPS):
  - "مدیران فنی": support. Sees the whole panel read-only to find what is wrong (sees_everything),
    edits only the site's own pages and contact channels, and runs «درخواست‌های فنی». Never the
    money, the office reports, anyone's CV or anyone's کارپوشه.
  - "مدیران مالی": the finance pages (see can_see_finance), and the store's orders, read only.
  - "مدیران اداری": watches the staff — directory, activity, performance — and reports to the site
    admins; decides nothing.
  Some doors are opened by the role in code, whatever the permissions: finance (can_see_finance),
  office (sees_office), «درخواست‌های فنی» and the کارپوشه.
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


def group_names(user):
    """
    The names of the person's groups, which is what every role question here comes down to.

    A panel page asks a dozen of them (the sidebar, each section's counter, each admin's access
    checks), and each used to be its own query. For the visitor of an admin page the answer is
    kept on their own user object for that one request (RoleCacheMiddleware marks it); any other
    user object is asked afresh, so a membership changed in code is never read back stale.
    """
    cached = getattr(user, "_mahay_group_names", None)
    if cached is not None:
        return cached
    names = frozenset(user.groups.values_list("name", flat=True)) if user.is_authenticated else frozenset()
    if getattr(user, "_mahay_cache_groups", False):
        user._mahay_group_names = names
    return names


def is_site_admin(user):
    """Superuser or member of a full-access group (works for any user object, even anonymous)."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or not group_names(user).isdisjoint(FULL_ACCESS_GROUPS)


def is_system_group(group):
    """Groups managed by the system: the full-access groups and every domain's two groups."""
    from domains.access import is_domain_group

    return group.name in OWNER_ONLY_GROUPS or is_domain_group(group)


# What the finance managers start with besides the finance app: the store's money records, read only
FINANCE_VIEWS = (("commerce", "order"), ("commerce", "orderitem"), ("commerce", "purchase"))

# Never given to a staff group, whoever ticks it: changing accounts, groups and permissions (a
# staff member could raise their own access with it), sessions, the admin's log, or the domains
# (making or removing one makes or removes its groups). Viewing any of these is allowed.
STAFF_WRITE_FORBIDDEN_APPS = ("auth", "contenttypes", "sessions", "admin", "accounts", "domains")


def staff_default_permissions(name):
    """
    What a staff group starts with. Site admins may change it in the panel afterwards; nothing
    puts it back by itself (the «دسترسی‌های پیش‌فرض» action does, when asked):
    - technical admins: viewing all but TECH_HIDDEN_APPS / TECH_HIDDEN_MODELS, changing TECH_EDITS
    - finance managers: the finance app, and viewing FINANCE_VIEWS
    - office managers: the office app
    """
    from django.db.models import Q

    if name == TECH_ADMINS_GROUP:
        edits = Q()
        for app_label, model in TECH_EDITS:
            edits |= Q(content_type__app_label=app_label, content_type__model=model)
        hidden = Q(content_type__app_label__in=TECH_HIDDEN_APPS)
        for app_label, model in TECH_HIDDEN_MODELS:
            hidden |= Q(content_type__app_label=app_label, content_type__model=model)
        return staff_permission_choices().exclude(hidden).filter(Q(codename__startswith="view_") | edits)
    if name == FINANCE_GROUP:
        views = Q()
        for app_label, model in FINANCE_VIEWS:
            views |= Q(content_type__app_label=app_label, content_type__model=model, codename__startswith="view_")
        return staff_permission_choices().filter(Q(content_type__app_label="finance") | views)
    if name == OFFICE_GROUP:
        return staff_permission_choices().filter(content_type__app_label="office")
    return Permission.objects.none()


def staff_permission_choices():
    """The permissions a staff group may be given: any view, and any change outside the forbidden apps."""
    from django.db.models import Q

    return Permission.objects.filter(
        Q(codename__startswith="view_") | ~Q(content_type__app_label__in=STAFF_WRITE_FORBIDDEN_APPS)
    )


def _record_given(group, permissions):
    from .models import StaffDefaultGiven

    StaffDefaultGiven.objects.bulk_create(
        [StaffDefaultGiven(group=group, permission=permission) for permission in permissions],
        ignore_conflicts=True,
    )


def apply_staff_default_permissions(group):
    """
    Give a staff group back whatever of its starting permissions it lacks (asked for in the panel);
    report what it holds beyond them. Only ever adds: one granted by hand was somebody's decision.
    """
    wanted = set(staff_default_permissions(group.name))
    held = set(group.permissions.all())
    missing = wanted - held
    group.permissions.add(*missing)
    _record_given(group, wanted)
    return missing, held - wanted


def ensure_site_admins_group():
    """
    Create the system's groups if missing (runs after every migrate). The site admins always hold
    every permission, new models' included.

    A staff group's permissions are the site admins' to set in the panel. A migrate only gives it
    the starting permissions it was never given before (StaffDefaultGiven) — a new model's, say —
    so one a site admin took away stays away.
    """
    from .models import StaffDefaultGiven

    site_admins, _ = Group.objects.get_or_create(name=SITE_ADMINS_GROUP)
    site_admins.permissions.set(Permission.objects.all())

    for name in STAFF_GROUPS:
        group, _ = Group.objects.get_or_create(name=name)
        given = StaffDefaultGiven.objects.filter(group=group).values("permission")
        new = list(staff_default_permissions(name).exclude(pk__in=given))
        if new:
            group.permissions.add(*new)
            _record_given(group, new)
    return site_admins


def in_group(user, name):
    return bool(user.is_authenticated and name in group_names(user))


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
    return in_group(user, FINANCE_GROUP)


def can_see_finance(user):
    return is_site_admin(user) or is_finance_manager(user)


def sync_staff_status(user_ids):
    """is_staff = superuser OR member of any group. Called whenever group memberships change."""
    from .models import User

    for user in User.objects.filter(pk__in=user_ids):
        should_be_staff = user.is_superuser or user.groups.exists()
        if user.is_staff != should_be_staff:
            User.objects.filter(pk=user.pk).update(is_staff=should_be_staff)