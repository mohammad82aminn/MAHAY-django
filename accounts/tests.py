from django.contrib.auth import authenticate
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import User
from .validators import normalize_mobile_number

CANONICAL = "+989121234567"
PASSWORD = "S3cure-pass!"


# --- Mobile number normalization ---------------------------------------------

class NormalizeMobileNumberTests(TestCase):
    def test_valid_formats(self):
        for value in (
            "09121234567", "9121234567", "+989121234567", "989121234567",
            "00989121234567", "۰۹۱۲۱۲۳۴۵۶۷", "٠٩١٢١٢٣٤٥٦٧", "0912 123 4567", "0912-123-4567",
        ):
            with self.subTest(value=value):
                self.assertEqual(normalize_mobile_number(value), CANONICAL)

    def test_invalid_formats(self):
        for value in ("", "abc", "0212345678", "091212345", "+19121234567", "081212345678"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    normalize_mobile_number(value)


# --- User manager -------------------------------------------------------------

class UserManagerTests(TestCase):
    def test_create_user_normalizes_mobile_and_email(self):
        user = User.objects.create_user("۰۹۱۲ ۱۲۳ ۴۵۶۷", PASSWORD, email=" Ali@Example.COM ")
        self.assertEqual(user.mobile_number, CANONICAL)
        self.assertEqual(user.email, "ali@example.com")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_same_number_in_other_format_is_duplicate(self):
        User.objects.create_user("09121234567", PASSWORD)
        with self.assertRaises(ValidationError):
            User.objects.create_user("+989121234567", PASSWORD)

    def test_invalid_mobile_rejected(self):
        with self.assertRaises(ValidationError):
            User.objects.create_user("abc", PASSWORD)

    def test_users_without_email_do_not_collide(self):
        User.objects.create_user("09121234567", PASSWORD, email="")
        user = User.objects.create_user("09351234567", PASSWORD)
        self.assertIsNone(user.email)

    def test_email_unique_case_insensitive(self):
        User.objects.create_user("09121234567", PASSWORD, email="a@b.com")
        with self.assertRaises(ValidationError):
            User.objects.create_user("09351234567", PASSWORD, email="A@B.com")

    def test_create_superuser(self):
        admin = User.objects.create_superuser("09121234567", PASSWORD)
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)


# --- Authentication backend -----------------------------------------------------

class LoginTests(TestCase):
    def setUp(self):
        User.objects.create_user("09121234567", PASSWORD)

    def test_login_with_any_mobile_format(self):
        for value in ("09121234567", "+989121234567", "۰۹۱۲۱۲۳۴۵۶۷"):
            with self.subTest(value=value):
                self.assertIsNotNone(authenticate(username=value, password=PASSWORD))

    def test_login_with_invalid_input_returns_none(self):
        self.assertIsNone(authenticate(username="abc", password=PASSWORD))


# --- Authentication pages -------------------------------------------------------

class SignUpViewTests(TestCase):
    url = reverse("accounts:signup")

    def test_signup_creates_user_and_logs_in(self):
        response = self.client.post(self.url, {
            "mobile_number": "۰۹۱۲ ۱۲۳ ۴۵۶۷",
            "first_name": "علی",
            "last_name": "رضایی",
            "password1": PASSWORD,
            "password2": PASSWORD,
        })
        self.assertRedirects(response, reverse("home"))
        user = User.objects.get()
        self.assertEqual(user.mobile_number, CANONICAL)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_signup_requires_name(self):
        response = self.client.post(self.url, {
            "mobile_number": "09121234567", "password1": PASSWORD, "password2": PASSWORD,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("first_name", response.context["form"].errors)
        self.assertFalse(User.objects.exists())

    def test_logged_in_user_is_redirected(self):
        self.client.force_login(User.objects.create_user("09121234567", PASSWORD))
        self.assertRedirects(self.client.get(self.url), reverse("home"))


class LoginLogoutViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("09121234567", PASSWORD, first_name="علی")

    def test_login_with_other_mobile_format(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": "+98 912 123 4567", "password": PASSWORD,
        })
        self.assertRedirects(response, reverse("home"))

    def test_login_wrong_password_shows_error(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": "09121234567", "password": "wrong-pass",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("accounts:logout")), reverse("home"))
        self.assertNotIn("_auth_user_id", self.client.session)


class ProfileViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("09121234567", PASSWORD, first_name="علی", last_name="رضایی")

    def test_requires_login(self):
        url = reverse("accounts:profile")
        self.assertRedirects(self.client.get(url), f"{reverse('accounts:login')}?next={url}")

    def test_update_profile(self):
        self.client.force_login(self.user)
        self.client.post(reverse("accounts:profile"), {
            "first_name": "علی", "last_name": "احمدی", "email": "Ali@Example.com",
        })
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_name, "احمدی")
        self.assertEqual(self.user.email, "ali@example.com")


class PasswordResetTests(TestCase):
    def test_reset_email_is_sent(self):
        User.objects.create_user("09121234567", PASSWORD, email="ali@example.com")
        response = self.client.post(reverse("accounts:password_reset"), {"email": "ali@example.com"})
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/password/reset/", mail.outbox[0].body)

    def test_unknown_email_sends_nothing_but_same_page(self):
        # Same response either way, so nobody can find out which emails are registered
        response = self.client.post(reverse("accounts:password_reset"), {"email": "no@example.com"})
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)