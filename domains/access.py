"""
Who holds which role in a domain. Every answer comes from group membership, never from the person.

- A domain *manager* is a member of its «مدیران حوزه» group; a domain may have several.
- A domain *expert* is a member of its «کارشناسان حوزه» group.
- A *member* is either: the people who see the domain's work at all.

Querysets filter with `<path>__in=member_domains(user)` (a subquery) rather than joining through
both groups, so a person in both of a domain's groups never makes a row appear twice.
"""
from .models import Domain


def member_domains(user):
    """Domains the person works in, as a manager or as an expert."""
    if not user.is_authenticated:
        return Domain.objects.none()
    return Domain.objects.filter(pk__in=_ids(user, "managers_group") | _ids(user, "experts_group"))


def managed_domains(user):
    """Domains the person manages."""
    if not user.is_authenticated:
        return Domain.objects.none()
    return Domain.objects.filter(managers_group__user=user)


def _ids(user, group_field):
    return Domain.objects.filter(**{f"{group_field}__user": user}).values("pk")


def is_member(user, domain):
    return member_domains(user).filter(pk=domain.pk).exists()


def is_manager(user, domain):
    return managed_domains(user).filter(pk=domain.pk).exists()


def has_managers(domain):
    """A domain nobody manages yet sends its experts' work straight to the site admins."""
    return domain.managers_group.user_set.filter(is_active=True).exists()


def domain_of_group(group):
    """(domain, "managers" | "experts") for one of a domain's groups, else (None, None)."""
    for kind in ("managers", "experts"):
        domain = getattr(group, f"{kind}_domain", None)
        if domain is not None:
            return domain, kind
    return None, None


def is_domain_group(group):
    return domain_of_group(group)[0] is not None
