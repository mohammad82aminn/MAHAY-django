import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class ProtectedStorage(FileSystemStorage):
    """
    Storage for paid files (lesson videos, attachments) in PROTECTED_MEDIA_ROOT.
    These files have NO public URL: they are sent only by content.views.protected_file after an access check.
    Moving to a cloud storage later = replacing this class, the models stay the same.
    """

    # Read from settings every time (not cached), so tests can point it to a temporary folder
    @property
    def base_location(self):
        return settings.PROTECTED_MEDIA_ROOT

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def url(self, name):
        return "#"  # never expose a direct link


protected_storage = ProtectedStorage()