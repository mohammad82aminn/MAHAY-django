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

    # Forgotten password: the account is reached by its mobile number, so a code proves it
    path("password/reset/", views.PasswordResetView.as_view(), name="password_reset"),
    path("password/reset/verify/", views.PasswordResetVerifyView.as_view(), name="password_reset_verify"),
    path("password/reset/verify/resend/", views.resend_reset_code, name="password_reset_resend"),
    path("password/reset/new/", views.PasswordResetNewView.as_view(), name="password_reset_new"),
]