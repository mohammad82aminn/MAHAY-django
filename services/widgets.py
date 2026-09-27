"""
The expert picker on a referral.

Which experts make sense depends on the domain chosen in the same row, and on a new referral
that domain has not been saved yet — so the server cannot narrow the list on its own. Every
expert is therefore rendered carrying the domains they manage, and referral_expert.js keeps only
the ones that fit the row. The queryset behind the field is still limited to domain managers, so
the page never carries the names of ordinary customers.
"""
from collections import defaultdict

from django import forms

from domains.models import Domain


def domains_by_manager():
    """{user id: [domain id, ...]} for everyone who works in a domain, in two queries."""
    mapping = defaultdict(set)
    for group_field in ("managers_group", "experts_group"):
        pairs = Domain.objects.filter(**{f"{group_field}__user__isnull": False}).values_list(f"{group_field}__user", "pk")
        for user_id, domain_id in pairs:
            mapping[str(user_id)].add(str(domain_id))
    return {user_id: sorted(domains) for user_id, domains in mapping.items()}


class ExpertSelect(forms.Select):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.domains = domains_by_manager()

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        managed = self.domains.get(str(getattr(value, "value", value)))
        if managed:
            option["attrs"]["data-domains"] = " ".join(managed)
        return option
