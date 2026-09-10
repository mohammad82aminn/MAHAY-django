from django.db.models.signals import m2m_changed, post_migrate
from django.dispatch import receiver

from .models import User
from .roles import ensure_site_admins_group, sync_staff_status


@receiver(post_migrate)
def create_site_admins_group(sender, **kwargs):
    # Runs after every "migrate", so new permissions (from new models) are added automatically
    ensure_site_admins_group()


@receiver(m2m_changed, sender=User.groups.through)
def update_staff_status(sender, instance, action, reverse, pk_set, **kwargs):
    """
    Keep is_staff in sync with group membership.
    reverse=False: instance is a User  (user.groups.add(...))
    reverse=True:  instance is a Group (group.user_set.add(...))
    """
    if reverse and action == "pre_clear":
        # Remember members before group.user_set.clear() removes them
        instance._cleared_user_ids = list(instance.user_set.values_list("pk", flat=True))
        return

    if action not in ("post_add", "post_remove", "post_clear"):
        return

    if not reverse:
        user_ids = [instance.pk]
    elif action == "post_clear":
        user_ids = getattr(instance, "_cleared_user_ids", [])
    else:
        user_ids = pk_set or []

    sync_staff_status(user_ids)