from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, FormView, UpdateView

from . import otp, sms
from .forms import LoginForm, ProfileForm, SignUpForm, VerifyCodeForm
from .models import User, VerificationCode

PENDING_SESSION_KEY = "signup_mobile"  # the number waiting for its code


def claim_guest_requests(user):
    """Attach requests this person sent before they had an account (imported late: services
    reaches into accounts, so importing it at module level would close a circle)."""
    from services.services import claim_guest_requests as claim

    claim(user)


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
            messages.success(self.request, f"{user.first_name} عزیز، به MAHAY خوش آمدید!")
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

    messages.success(request, "کد تأیید پیامک شد.")
    if settings.DEBUG:  # development only: the terminal is not in front of the tester
        messages.info(request, f"حالت آزمایشی — کد شما: {code}")


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
            form.add_error("code", "کد تأیید نادرست یا منقضی شده است.")
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
        messages.success(self.request, f"{user.first_name} عزیز، شماره‌ی شما تأیید شد. به MAHAY خوش آمدید!")
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
    success_message = "اطلاعات شما ذخیره شد."

    def get_object(self, queryset=None):
        return self.request.user


class PasswordChangeView(SuccessMessageMixin, auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")
    success_message = "رمز عبور شما تغییر کرد."


class PasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/emails/password_reset_email.txt"
    subject_template_name = "accounts/emails/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")