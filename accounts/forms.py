from django.contrib.auth import forms as auth_forms

from .models import User

USER_CREATION_FIELDS = ("mobile_number", "email", "first_name", "last_name")


class UserCreationForm(auth_forms.BaseUserCreationForm):
    """Sign-up form for the website (used in the Authentication step)."""

    class Meta:
        model = User
        fields = USER_CREATION_FIELDS


class AdminUserCreationForm(auth_forms.AdminUserCreationForm):
    """Admin "add user" form; also allows creating users without a usable password."""

    class Meta:
        model = User
        fields = USER_CREATION_FIELDS


class UserChangeForm(auth_forms.UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"