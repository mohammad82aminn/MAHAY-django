"""
Who may apply, who may read an application, and what counts as one still being open.
"""
from .models import CollaborationRequest


def may_apply(user):
    """
    Anybody with an account, except the people who already work here.

    Offering «همکاری با مجموعه» to somebody who is already a domain manager would be an odd
    thing to say to them, and is_staff is exactly the test for holding a role.
    """
    return bool(user.is_authenticated and not user.is_staff)


def open_request(user):
    """The application waiting on an answer, if there is one."""
    if not user.is_authenticated:
        return None
    return CollaborationRequest.objects.filter(
        user=user, status__in=CollaborationRequest.OPEN_STATUSES,
    ).first()


def latest_request(user):
    """What to show the applicant: the newest, open or closed."""
    if not user.is_authenticated:
        return None
    return CollaborationRequest.objects.filter(user=user).prefetch_related("files", "domains").first()


def can_read_files(user, request_object):
    """
    The applicant's own documents, and whoever is allowed to review applications.

    The review permission is what decides, not a hard-coded role: the site admins hold every
    permission already, and the owner can hand this one to somebody else later without a
    change here.
    """
    if not user.is_authenticated:
        return False
    if request_object.user_id == user.pk:
        return True
    return user.has_perm("collaboration.view_collaborationrequest")
