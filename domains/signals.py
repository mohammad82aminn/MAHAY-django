from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver

from accounts.roles import sync_staff_status

from .models import Domain


@receiver(pre_delete, sender=Domain)
def remember_domain_managers(sender, instance, **kwargs):
    instance._manager_ids = list(instance.group.user_set.values_list("pk", flat=True))


@receiver(post_delete, sender=Domain)
def delete_domain_group(sender, instance, **kwargs):
    # Deleting a domain removes its group; former managers lose admin access if they have no other group
    instance.group.delete()
    sync_staff_status(getattr(instance, "_manager_ids", []))