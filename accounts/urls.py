from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.SignUpView.as_view(), name="signup"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("signup/verify/", views.VerifyView.as_view(), name="verify"),
    path("signup/verify/resend/", views.resend_code, name="resend_code"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("password/change/", views.PasswordChangeView.as_view(), name="password_change"),

    # Forgot password (by email). SMS reset will be added next to these later.
    path("password/reset/", views.PasswordResetView.as_view(), name="password_reset"),
    path(
        "password/reset/sent/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/message.html",
            extra_context={
                "title": "ایمیل ارسال شد",
                "text": "اگر حسابی با این ایمیل وجود داشته باشد، لینک تعیین رمز جدید برایتان ارسال شد. "
                        "صندوق ورودی و پوشه‌ی Spam را بررسی کنید.",
            },
        ),
        name="password_reset_done",
    ),
    path("password/reset/<uidb64>/<token>/", views.PasswordResetConfirmView.as_view(),
         name="password_reset_confirm"),
    path(
        "password/reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/message.html",
            extra_context={
                "title": "رمز عبور تغییر کرد",
                "text": "رمز جدید شما ثبت شد. اکنون می‌توانید وارد شوید.",
                "show_login": True,
            },
        ),
        name="password_reset_complete",
    ),
]