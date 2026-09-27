"""
Dividing a receipt into shares.

A receipt is first cut into portions, one per domain it belongs to: a store sale belongs wholly to
its product's domain; a payment for a project order is spread over the domains it was referred to,
in proportion to each domain's agreed price (evenly, while any price is still missing). Each portion
is then divided by that domain's percentages — or by an exception set on the product or the order —
among the instructors or the expert, the domain's managers, the domain's fund, and the collection,
which keeps whatever is left.

Amounts are whole tomans, always rounded down; what rounding leaves over goes to the collection, so
a receipt's shares always add up to exactly its amount. When something needed is missing (no
percentages yet, no expert chosen, nobody in a role that has a percentage) nothing is divided and
the receipt says why, until someone divides it again.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import DomainShareRule, ProductShareRule, Receipt, RequestShareRule, Share


class NotYet(Exception):
    """Something the division needs is missing; the message says what."""


def split(receipt):
    """Divide the receipt, replacing any earlier division. Returns True when it could be divided."""
    if receipt.is_void:
        return False
    with transaction.atomic():
        receipt.shares.all().delete()
        try:
            shares = [share for portion in _portions(receipt) for share in _divide(receipt, *portion)]
        except NotYet as reason:
            receipt.split_at, receipt.unsplit_reason = None, str(reason)[:250]
            receipt.save(update_fields=["split_at", "unsplit_reason"])
            return False
        Share.objects.bulk_create(shares)
        receipt.split_at, receipt.unsplit_reason = timezone.now(), ""
        receipt.save(update_fields=["split_at", "unsplit_reason"])
    return True


# --- Portions: which domain each part of the money belongs to -------------------------

def _portions(receipt):
    """[(domain, amount, percents, people by role), ...] adding up to the receipt's amount."""
    if receipt.source == Receipt.Source.SALE:
        return [_sale_portion(receipt)]
    return _service_portions(receipt)


def _sale_portion(receipt):
    product = receipt.product
    if product is None:
        raise NotYet("محصول این دریافت دیگر وجود ندارد.")
    domain = product.primary_domain
    percents = _filled(ProductShareRule, product=product) or _domain_rule(domain).sale_percents()
    if percents is None:
        raise NotYet(f"درصدهای سهم فروش حوزه‌ی {domain} تعیین نشده است.")
    people = {
        Share.Role.INSTRUCTOR: [person for person in product.instructors.all() if person.is_active],
        Share.Role.MANAGER: _managers(domain),
    }
    return domain, receipt.amount, percents, people


def _service_portions(receipt):
    from services.models import Referral

    request = receipt.service_request
    if request is None:
        raise NotYet("درخواست این دریافت دیگر وجود ندارد.")
    referrals = list(
        request.referrals.exclude(status=Referral.Status.NOT_FEASIBLE).select_related("domain", "expert").order_by("pk")
    )
    if not referrals:
        raise NotYet("این درخواست هنوز به حوزه‌ای ارجاع نشده است.")

    prices = [referral.quoted_price if referral.quote_approved_at else None for referral in referrals]
    weights = prices if all(prices) else [1] * len(referrals)  # evenly until every price is agreed
    amounts = _spread(receipt.amount, weights)

    exception = _filled(RequestShareRule, request=request)
    portions = []
    for referral, amount in zip(referrals, amounts):
        percents = exception or _domain_rule(referral.domain).service_percents()
        if percents is None:
            raise NotYet(f"درصدهای سهم سفارش حوزه‌ی {referral.domain} تعیین نشده است.")
        expert = referral.expert if referral.expert and referral.expert.is_active else None
        people = {
            Share.Role.EXPERT: [expert] if expert else [],
            Share.Role.MANAGER: _managers(referral.domain),
        }
        portions.append((referral.domain, amount, percents, people))
    return portions


def _spread(total, weights):
    """Split a whole number in proportion to the weights, rounding down; the first part takes the rest."""
    whole = sum(weights)
    parts = [total * weight // whole for weight in weights]
    parts[0] += total - sum(parts)
    return parts


# --- Dividing one portion -------------------------------------------------------------

ROLE_ORDER = (Share.Role.INSTRUCTOR, Share.Role.EXPERT, Share.Role.MANAGER, Share.Role.FUND)
MISSING = {
    Share.Role.INSTRUCTOR: "مدرسی برای این محصول انتخاب نشده است",
    Share.Role.EXPERT: "کارشناسی برای کار حوزه‌ی {domain} انتخاب نشده است",
    Share.Role.MANAGER: "حوزه‌ی {domain} مدیری ندارد",
}


def _divide(receipt, domain, amount, percents, people):
    shares = []
    for role in ROLE_ORDER:
        percent = percents.get(role)
        if not percent:
            continue
        part = int(Decimal(amount) * percent // 100)
        if role == Share.Role.FUND:
            shares.append(Share(receipt=receipt, domain=domain, role=role, percent=percent, amount=part))
            continue
        receivers = people.get(role, [])
        if not receivers:
            raise NotYet(MISSING[role].format(domain=domain) + f"، اما برای آن {percent}٪ سهم تعیین شده است.")
        each = part // len(receivers)
        for person in receivers:
            shares.append(Share(receipt=receipt, domain=domain, role=role, person=person,
                                percent=percent / len(receivers), amount=each))
    rest = amount - sum(share.amount for share in shares)
    shares.append(Share(receipt=receipt, domain=domain, role=Share.Role.COMPANY, amount=rest))
    return shares


def _domain_rule(domain):
    rule, _created = DomainShareRule.objects.get_or_create(domain=domain)
    return rule


def _filled(model, **lookup):
    rule = model.objects.filter(**lookup).first()
    return rule.percents() if rule is not None else None


def _managers(domain):
    return [person for person in domain.managers_group.user_set.order_by("pk") if person.is_active]
