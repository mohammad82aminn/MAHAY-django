"""
Who may open protected files (videos, attachments, thesis) of a product:
- the buyer (a Purchase row exists — it stays valid even if the product leaves the store)
- the people of the product's domain (its managers and experts), site admins (to check the content),
  and the technical admins (to see why a video won't play)

A lesson ticked «قابل مشاهده بدون خرید» opens its video and text to everyone (is_open_sample).

A buyer gets only what has been approved: a lesson, a lesson's file or a companion file still
waiting for review (or removed) is not theirs yet, even if they guess its address. The people who
review it see it as it is.
"""
from accounts.roles import sees_everything
from domains.access import is_member


def can_manage(user, product):
    return sees_everything(user) or is_member(user, product.primary_domain)


def owns(user, product):
    from commerce.models import Purchase

    return Purchase.objects.filter(user=user, product=product).exists()


def can_open(user, product):
    if not user.is_authenticated:
        return False
    return owns(user, product) or can_manage(user, product)


def is_live(item):
    """
    Approved and on show, together with everything it sits in: a lesson and its section, a file and
    its lesson and section, a companion file. A product (its thesis) has no such state for a buyer:
    what they bought stays theirs even after the product leaves the store.
    """
    from .models import Attachment, Lesson, ProductFile

    def shown(obj):
        return obj.is_published and not obj.is_archived

    if isinstance(item, Attachment):
        return shown(item) and is_live(item.lesson)
    if isinstance(item, Lesson):
        return shown(item) and shown(item.section)
    if isinstance(item, ProductFile):
        return shown(item)
    return True


def is_open_sample(lesson):
    """
    A lesson anyone may watch without buying: ticked «قابل مشاهده بدون خرید», approved and on show
    (with its section), in a paid product that is in the store. A free product has no samples: it is
    ordered for nothing and opened whole.
    """
    from products.models import Product

    if not lesson.is_free_preview or not is_live(lesson):
        return False
    product = lesson.product
    return not product.is_free and Product.objects.visible().filter(pk=product.pk).exists()


def can_open_item(user, item):
    """can_open for one protected thing of a product, not just the product."""
    if not user.is_authenticated:
        return False
    product = getattr(item, "product", item)
    if can_manage(user, product):
        return True
    return owns(user, product) and is_live(item)
