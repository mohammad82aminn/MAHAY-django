"""
Who may use the کارپوشه, who may see what, and how a message is sent.

One rule decides everything: a person is part of a message only as its sender or as one of its
recipients. Nobody — site admins included — gets a way to read a conversation they are not in,
which is why these models are kept out of the normal admin registry altogether.
"""
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Count, Q

from accounts.models import User

from .models import Delivery, Message


def has_inbox(user):
    """
    Anyone holding a role has a کارپوشه; a customer has none.

    is_staff is kept in step with group membership (accounts.roles.sync_staff_status), so someone
    dropped from every group loses the کارپوشه with the rest of the panel, while someone who only
    moves between domains keeps theirs.
    """
    return bool(user.is_authenticated and user.is_staff)


def visible_messages(user):
    """Messages this person sent or received. Every query starts here."""
    return Message.objects.filter(Q(sender=user) | Q(deliveries__user=user)).distinct()


def can_read(user, message):
    return has_inbox(user) and visible_messages(user).filter(pk=message.pk).exists()


def received(user, archived=False):
    """The person's own deliveries, newest first."""
    return (
        Delivery.objects.filter(user=user, archived_at__isnull=not archived)
        .select_related("message", "message__sender")
        .prefetch_related("message__files")
    )


def sent(user, archived=False):
    """
    The person's own outbox. Both counts are annotated rather than read per row, so a long
    outbox stays one query instead of two more for every message in it.
    """
    return (
        Message.objects.filter(sender=user, sender_archived_at__isnull=not archived)
        .annotate(
            recipient_count=Count("deliveries", distinct=True),
            read_count=Count("deliveries", filter=Q(deliveries__read_at__isnull=False), distinct=True),
        )
        .prefetch_related("files")
    )


def unread_count(user):
    """One COUNT for the badge. Callers must check has_inbox() first."""
    return Delivery.objects.filter(user=user, read_at__isnull=True, archived_at__isnull=True).count()


def addressable_groups():
    """The groups a message may be sent to, i.e. every role in the site."""
    return Group.objects.all().order_by("name")


def addressable_users(exclude=None):
    """
    Everyone who has a کارپوشه, so they can be picked as a recipient.

    The test is is_staff, the same one has_inbox() uses, and not group membership: the site owner
    is a superuser who belongs to no group, so asking for a group here left the one person
    everybody needs to answer unreachable.

    Only the name and the roles are ever shown — never a phone number: the کارپوشه is open to
    every colleague and must not become the staff phone book.
    """
    people = User.objects.filter(is_active=True, is_staff=True)
    if exclude is not None:
        people = people.exclude(pk=exclude.pk)
    return people.prefetch_related("groups").order_by("first_name", "last_name")


def resolve_recipients(users=(), groups=(), everyone=False, exclude=None):
    """
    Turn what the sender picked into the actual set of people.

    Groups are expanded here, at send time: their members become recipients in their own right,
    so a later arrival to the group never gains access to this message.
    """
    if everyone:
        people = User.objects.filter(is_active=True, is_staff=True)
    else:
        people = User.objects.filter(
            Q(pk__in=[user.pk for user in users]) | Q(groups__in=list(groups)),
            is_active=True, is_staff=True,
        )
    people = people.distinct()
    if exclude is not None:
        people = people.exclude(pk=exclude.pk)
    return list(people)


@transaction.atomic
def send(sender, subject, body, recipients, parent=None, files=()):
    """Store the message and hand each recipient their own copy. Returns the message."""
    message = Message.objects.create(
        sender=sender, from_system=sender is None, subject=subject, body=body, parent=parent,
    )
    Delivery.objects.bulk_create([Delivery(message=message, user=person) for person in recipients])
    for uploaded in files:
        message.files.create(file=uploaded)
    return message
