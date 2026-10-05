from django import forms
from django.contrib.auth import forms as auth_forms
from django.utils.translation import gettext_lazy as _

from .models import User
from . import throttle
from .otp import CODE_LENGTH
from .validators import DIGIT_MAP, normalize_mobile_number

# Mobile input: left-to-right, numeric keyboard on phones, raw input may contain spaces
MOBILE_ATTRS = {
    "dir": "ltr",
    "inputmode": "tel",
    "autocomplete": "tel",
    "placeholder": "0912 345 6789",
    "maxlength": 20,
}


class SignUpForm(auth_forms.BaseUserCreationForm):
    """Website sign-up: mobile, name, an optional email, and a password."""

    class Meta:
        model = User
        fields = ("mobile_number", "first_name", "last_name", "email")
        widgets = {
            "mobile_number": forms.TextInput(attrs=MOBILE_ATTRS),
            "email": forms.EmailInput(attrs={"dir": "ltr", "autocomplete": "email"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.fields["mobile_number"].widget.attrs["autofocus"] = True
        # The account is reached by mobile number; an email is only a way to contact the person.
        # Two people leaving it empty do not clash: the model stores an empty one as NULL.
        self.fields["email"].help_text = _("اختیاری")

    def clean_mobile_number(self):
        number = self.cleaned_data["mobile_number"]
        unverified = User.objects.filter(mobile_number=number, mobile_verified=False, is_active=False).first()
        if unverified is not None:
            self.instance = unverified  # continue the unfinished sign-up instead of refusing the number
        return number


class PasswordResetRequestForm(forms.Form):
    """
    Step one of a forgotten password: which number.

    Whether that number has an account is never said here — see the view. Answering would turn
    this page into a way of finding out who is registered.
    """

    mobile_number = forms.CharField(label=_("شماره موبایل"), max_length=20,
                                    widget=forms.TextInput(attrs={**MOBILE_ATTRS, "autofocus": True}))

    def clean_mobile_number(self):
        return normalize_mobile_number(self.cleaned_data["mobile_number"])


class VerifyCodeForm(forms.Form):
    """The 6-digit code sent by SMS."""

    code = forms.CharField(
        label=_("کد تأیید"), max_length=CODE_LENGTH, min_length=CODE_LENGTH,
        widget=forms.TextInput(attrs={
            "dir": "ltr", "inputmode": "numeric", "autocomplete": "one-time-code",
            "placeholder": "------", "autofocus": True, "class": "code-input",
        }),
    )

    def clean_code(self):
        # Persian digits are typed on many phone keyboards
        code = self.cleaned_data["code"].translate(DIGIT_MAP).strip()
        if not code.isdigit():
            raise forms.ValidationError(_("کد تأیید فقط عدد است."))
        return code

class LoginForm(auth_forms.AuthenticationForm):
    """Login with mobile number in any format (0912..., +98912..., Persian digits)."""

    error_messages = {
        **auth_forms.AuthenticationForm.error_messages,
        "inactive": _("شماره‌ی این حساب تأیید نشده است. دوباره ثبت‌نام کنید تا کد تأیید برایتان ارسال شود."),
        "blocked": _("تلاش‌های ناموفق زیادی انجام شده است. %(minutes)s دقیقه دیگر دوباره تلاش کنید."),
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].widget.attrs.update(MOBILE_ATTRS)
        self.fields["password"].widget.attrs["dir"] = "ltr"

    def clean(self):
        number = self.data.get("username", "")
        try:
            number = normalize_mobile_number(number)
        except forms.ValidationError:
            number = ""
        ip_address = throttle.client_ip(self.request)

        blocked = throttle.minutes_blocked(number, ip_address)
        if blocked:
            raise forms.ValidationError(
                self.error_messages["blocked"], code="blocked", params={"minutes": blocked},
            )

        try:
            data = super().clean()
        except forms.ValidationError:
            throttle.record_failure(number, ip_address)
            raise
        return data

    def get_invalid_login_error(self):
        # Django refuses inactive users with the generic message; say what is really wrong
        number = self.cleaned_data.get("username")
        waiting = User.objects.filter(mobile_number=number, is_active=False, mobile_verified=False).exists()
        return forms.ValidationError(
            self.error_messages["inactive" if waiting else "invalid_login"],
            code="inactive" if waiting else "invalid_login",
            params={"username": self.username_field.verbose_name},
        )

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
        widgets = {"mobile_number": forms.TextInput(attrs=MOBILE_ATTRS)}


class UserChangeForm(auth_forms.UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"
        widgets = {"mobile_number": forms.TextInput(attrs=MOBILE_ATTRS)}