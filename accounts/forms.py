from django import forms
from django.contrib.auth import forms as auth_forms

from .models import User

# Mobile input: left-to-right, numeric keyboard on phones, raw input may contain spaces
MOBILE_ATTRS = {
    "dir": "ltr",
    "inputmode": "tel",
    "autocomplete": "tel",
    "placeholder": "0912 345 6789",
    "maxlength": 20,
}


class SignUpForm(auth_forms.BaseUserCreationForm):
    """Website sign-up: mobile, name and password (email is added later in profile)."""

    class Meta:
        model = User
        fields = ("mobile_number", "first_name", "last_name")
        widgets = {"mobile_number": forms.TextInput(attrs=MOBILE_ATTRS)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.fields["mobile_number"].widget.attrs["autofocus"] = True


class LoginForm(auth_forms.AuthenticationForm):
    """Login with mobile number in any format (0912..., +98912..., Persian digits)."""

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].widget.attrs.update(MOBILE_ATTRS)
        self.fields["password"].widget.attrs["dir"] = "ltr"


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")
        widgets = {"email": forms.EmailInput(attrs={"dir": "ltr", "autocomplete": "email"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True


# --- Admin forms ------------------------------------------------------------

class AdminUserCreationForm(auth_forms.AdminUserCreationForm):
    """Admin "add user" form; also allows creating users without a usable password."""

    class Meta:
        model = User
        fields = ("mobile_number", "email", "first_name", "last_name")


class UserChangeForm(auth_forms.UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"