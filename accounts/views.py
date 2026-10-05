from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import CreateView, FormView, UpdateView

from django.contrib.auth.forms import SetPasswordForm
from django.views.generic import FormView

from . import otp, sms
from .forms import LoginForm, PasswordResetRequestForm, ProfileForm, SignUpForm, VerifyCodeForm
from .models import User, VerificationCode

PENDING_SESSION_KEY = "signup_mobile"  # the number waiting for its code

# If one of these pages fails, the error report (log, email) shows these fields as ******** —
# Django's own login and password-change pages already do the same
SECRET_FIELDS = sensitive_post_parameters("password", "password1", "password2", "new_password1", "new_password2", "code")


def claim_guest_requests(user):
    """Attach requests this person sent before they had an account (imported late: services
    reaches into accounts, so importing it at module level would close a circle)."""
    from services.services import claim_guest_requests as claim

    claim(user)


@method_decorator(SECRET_FIELDS, name="dispatch")
class SignUpView(CreateView):
    form_class = SignUpForm
    template_name = "accounts/signup.html"

    def dispatch(self, request, *args, **kwargs):
        # Logged-in users have no reason to see the sign-up page
        if request.user.is_authenticated:
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save(commit=False)
        if not sms.is_enabled():
            # No SMS provider: keep sign-up in one step
            user.is_active = True
            user.save()
            claim_guest_requests(user)
            login(self.request, user)
            messages.success(self.request, _("%(name)s عزیز، به MAHAY خوش آمدید!") % {"name": user.first_name})
            return redirect("home")

        user.is_active = False  # activated by the code
        user.mobile_verified = False
        user.save()
        self.request.session[PENDING_SESSION_KEY] = user.mobile_number
        send_code(self.request, user.mobile_number)
        return redirect("accounts:verify")

def send_code(request, mobile_number):
    """Send a sign-up code and tell the user what happened."""
    try:
        code = otp.create_and_send(mobile_number, VerificationCode.Purpose.SIGNUP)
    except otp.TooManyRequests as error:
        messages.warning(request, str(error))
        return
    except sms.SMSError as error:
        messages.error(request, str(error))
        return

    messages.success(request, _("کد تأیید پیامک شد."))
    if settings.DEBUG:  # development only: the terminal is not in front of the tester
        messages.info(request, _("حالت آزمایشی — کد شما: %(code)s") % {"code": code})


@method_decorator(SECRET_FIELDS, name="dispatch")
class VerifyView(FormView):
    """Step 2 of sign-up: the code that was sent by SMS."""

    form_class = VerifyCodeForm
    template_name = "accounts/verify.html"

    def dispatch(self, request, *args, **kwargs):
        self.mobile_number = request.session.get(PENDING_SESSION_KEY)
        if not self.mobile_number:
            return redirect("accounts:signup")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = User.objects.filter(mobile_number=self.mobile_number).first()
        context["mobile_display"] = user.mobile_display if user else self.mobile_number
        context["resend_in"] = otp.seconds_until_resend(self.mobile_number, VerificationCode.Purpose.SIGNUP)
        return context

    def form_valid(self, form):
        if not otp.verify(self.mobile_number, VerificationCode.Purpose.SIGNUP, form.cleaned_data["code"]):
            form.add_error("code", _("کد تأیید نادرست یا منقضی شده است."))
            return self.form_invalid(form)

        user = User.objects.filter(mobile_number=self.mobile_number).first()
        if user is None:
            return redirect("accounts:signup")

        user.is_active = True
        user.mobile_verified = True
        user.save(update_fields=["is_active", "mobile_verified"])
        claim_guest_requests(user)
        self.request.session.pop(PENDING_SESSION_KEY, None)
        login(self.request, user)
        messages.success(self.request, _("%(name)s عزیز، شماره‌ی شما تأیید شد. به MAHAY خوش آمدید!") % {"name": user.first_name})
        return redirect("home")


def resend_code(request):
    """"Send the code again" button on the verification page."""
    mobile_number = request.session.get(PENDING_SESSION_KEY)
    if not mobile_number:
        return redirect("accounts:signup")
    send_code(request, mobile_number)
    return redirect("accounts:verify")


class LoginView(auth_views.LoginView):
    form_class = LoginForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True


class ProfileView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    form_class = ProfileForm
    template_name = "accounts/profile.html"
    success_url = reverse_lazy("accounts:profile")
    success_message = gettext_lazy("اطلاعات شما ذخیره شد.")

    def get_object(self, queryset=None):
        return self.request.user


class PasswordChangeView(SuccessMessageMixin, auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")
    success_message = gettext_lazy("رمز عبور شما تغییر کرد.")


# --- Forgotten password, by SMS code ----------------------------------------------
#
# Sign-up never asked for an email, so an emailed reset link could not reach most people. The
# account is reached by its mobile number, so that is what proves ownership here too.

RESET_SESSION_KEY = "reset_mobile"  # the number a reset is running for
RESET_VERIFIED_KEY = "reset_verified"  # the same number again, once its code has been entered


def resettable_user(mobile_number):
    """
    Who may have their password reset: a finished account.

    An account whose number was never confirmed is left out on purpose. Signing up again picks
    that unfinished account back up and sends a fresh code, and having two ways in would mean
    one of them could be used to activate an account the person never proved was theirs.
    """
    return User.objects.filter(mobile_number=mobile_number, is_active=True, mobile_verified=True).first()


class PasswordResetView(FormView):
    """Step one: ask for the number and send a code to it."""

    form_class = PasswordResetRequestForm
    template_name = "accounts/password_reset.html"
    success_url = reverse_lazy("accounts:password_reset_verify")

    def form_valid(self, form):
        mobile_number = form.cleaned_data["mobile_number"]
        self.request.session[RESET_SESSION_KEY] = mobile_number
        self.request.session.pop(RESET_VERIFIED_KEY, None)

        # The next page looks the same whether or not this number has an account: saying so
        # would let anyone use this form to find out who is registered.
        if resettable_user(mobile_number) is not None:
            try:
                code = otp.create_and_send(mobile_number, VerificationCode.Purpose.PASSWORD_RESET)
            except otp.TooManyRequests as error:
                messages.warning(self.request, str(error))
                return super().form_valid(form)
            if settings.DEBUG:
                messages.info(self.request, _("حالت آزمایشی — کد شما: %(code)s") % {"code": code})
        return super().form_valid(form)


@method_decorator(SECRET_FIELDS, name="dispatch")
class PasswordResetVerifyView(FormView):
    """Step two: the code that was sent."""

    form_class = VerifyCodeForm
    template_name = "accounts/password_reset_verify.html"
    success_url = reverse_lazy("accounts:password_reset_new")

    def dispatch(self, request, *args, **kwargs):
        self.mobile_number = request.session.get(RESET_SESSION_KEY)
        if not self.mobile_number:
            return redirect("accounts:password_reset")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = resettable_user(self.mobile_number)
        context["mobile_display"] = user.mobile_display if user else self.mobile_number
        context["resend_in"] = otp.seconds_until_resend(
            self.mobile_number, VerificationCode.Purpose.PASSWORD_RESET
        )
        return context

    def form_valid(self, form):
        code = form.cleaned_data["code"]
        if not otp.verify(self.mobile_number, VerificationCode.Purpose.PASSWORD_RESET, code):
            form.add_error("code", _("کد تأیید نادرست یا منقضی شده است."))
            return self.form_invalid(form)

        # Kept beside the number rather than as a bare flag, so a later step cannot be pointed
        # at a different account by changing only the number in the session.
        self.request.session[RESET_VERIFIED_KEY] = self.mobile_number
        return super().form_valid(form)


def resend_reset_code(request):
    mobile_number = request.session.get(RESET_SESSION_KEY)
    if not mobile_number:
        return redirect("accounts:password_reset")

    if resettable_user(mobile_number) is not None:
        try:
            code = otp.create_and_send(mobile_number, VerificationCode.Purpose.PASSWORD_RESET)
        except otp.TooManyRequests as error:
            messages.warning(request, str(error))
        else:
            messages.success(request, _("کد تأیید دوباره فرستاده شد."))
            if settings.DEBUG:
                messages.info(request, _("حالت آزمایشی — کد شما: %(code)s") % {"code": code})
    return redirect("accounts:password_reset_verify")


@method_decorator(SECRET_FIELDS, name="dispatch")
class PasswordResetNewView(FormView):
    """Step three: the new password, for a number whose code was just entered."""

    form_class = SetPasswordForm
    template_name = "accounts/password_reset_new.html"
    success_url = reverse_lazy("accounts:login")

    def dispatch(self, request, *args, **kwargs):
        mobile_number = request.session.get(RESET_SESSION_KEY)
        if not mobile_number or request.session.get(RESET_VERIFIED_KEY) != mobile_number:
            return redirect("accounts:password_reset")
        self.user = resettable_user(mobile_number)
        if self.user is None:
            return redirect("accounts:password_reset")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.user}

    def form_valid(self, form):
        form.save()
        # The proof is spent: it must not reset a second password later
        self.request.session.pop(RESET_SESSION_KEY, None)
        self.request.session.pop(RESET_VERIFIED_KEY, None)
        messages.success(self.request, _("رمز عبور شما تغییر کرد. اکنون وارد شوید."))
        return super().form_valid(form)