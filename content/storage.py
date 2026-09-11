from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible
from django.utils.functional import cached_property


@deconstructible
class ProtectedStorage(FileSystemStorage):
    """
    Storage for paid files (lesson videos, attachments) in PROTECTED_MEDIA_ROOT.
    These files have NO public URL: they are sent only by content.views.protected_file after an access check.
    Moving to a cloud storage later = replacing this class, the models stay the same.
    """

    @cached_property
    def base_location(self):
        return settings.PROTECTED_MEDIA_ROOT

    def url(self, name):
        return "#"  # never expose a direct link

    def _clear_cached_properties(self, setting, **kwargs):
        super()._clear_cached_properties(setting, **kwargs)
        if setting == "PROTECTED_MEDIA_ROOT":  # lets tests use a temporary folder
            self.__dict__.pop("base_location", None)
            self.__dict__.pop("location", None)


protected_storage = ProtectedStorage()