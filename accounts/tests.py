from unittest.mock import patch

from django.contrib.auth import authenticate
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from domains.models import Domain

from . import otp
from .models import User, VerificationCode
from .roles import role_label
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
@override_settings(SMS_BACKEND="disabled")  # sign-up verification has its own test file
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
    """
    Sign-up never asked for an email, so the account's own mobile number is what proves
    ownership. The number is also what must not be given away by this form.
    """

    NEW_PASSWORD = "An0ther-pass!"

    def setUp(self):
        self.user = User.objects.create_user("09121234567", PASSWORD, first_name="علی")
        self.user.mobile_verified = True
        self.user.save(update_fields=["mobile_verified"])

    def ask(self, number="09121234567"):
        return self.client.post(reverse("accounts:password_reset"), {"mobile_number": number})

    def sent_code(self):
        return VerificationCode.objects.filter(purpose=VerificationCode.Purpose.PASSWORD_RESET).first()

    def reach_the_new_password_page(self):
        self.ask()
        self.client.post(reverse("accounts:password_reset_verify"), {"code": "111111"})

    # --- the happy path -----------------------------------------------------------

    def test_a_code_is_sent_and_the_password_can_be_changed(self):
        with patch("accounts.otp.get_random_string", return_value="424242"):
            self.ask()
        self.assertIsNotNone(self.sent_code())

        response = self.client.post(reverse("accounts:password_reset_verify"), {"code": "424242"})
        self.assertRedirects(response, reverse("accounts:password_reset_new"))

        response = self.client.post(reverse("accounts:password_reset_new"), {
            "new_password1": self.NEW_PASSWORD, "new_password2": self.NEW_PASSWORD,
        })
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertIsNotNone(authenticate(username="09121234567", password=self.NEW_PASSWORD))

    def test_the_reset_code_lives_longer_than_a_sign_up_code(self):
        # A real provider adds delay, and this message is usually read later
        self.assertGreater(otp.RESET_CODE_TTL, otp.CODE_TTL)

    # --- what the form must not give away -----------------------------------------

    def test_an_unknown_number_looks_exactly_like_a_known_one(self):
        known = self.ask()
        unknown = self.ask("09350000000")
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.url, unknown.url)
        self.assertEqual(
            VerificationCode.objects.filter(mobile_number="+989350000000").count(), 0
        )

    def test_an_unverified_account_gets_no_code(self):
        # Signing up again picks that account back up; reset must not be a second way in
        User.objects.create_user("09351234567", PASSWORD, is_active=False)
        self.ask("09351234567")
        self.assertEqual(
            VerificationCode.objects.filter(mobile_number="+989351234567").count(), 0
        )

    # --- the steps cannot be jumped ------------------------------------------------

    def test_the_code_page_needs_a_request_first(self):
        response = self.client.get(reverse("accounts:password_reset_verify"))
        self.assertRedirects(response, reverse("accounts:password_reset"))

    def test_the_new_password_page_needs_a_verified_code(self):
        self.ask()  # asked, but never entered the code
        response = self.client.get(reverse("accounts:password_reset_new"))
        self.assertRedirects(response, reverse("accounts:password_reset"))

    def test_a_wrong_code_does_not_open_the_next_step(self):
        self.ask()
        response = self.client.post(reverse("accounts:password_reset_verify"), {"code": "000000"})
        self.assertContains(response, "نادرست")
        self.assertRedirects(
            self.client.get(reverse("accounts:password_reset_new")),
            reverse("accounts:password_reset"),
        )

    def test_the_proof_is_spent_once_the_password_is_set(self):
        with patch("accounts.otp.get_random_string", return_value="424242"):
            self.ask()
        self.client.post(reverse("accounts:password_reset_verify"), {"code": "424242"})
        self.client.post(reverse("accounts:password_reset_new"), {
            "new_password1": self.NEW_PASSWORD, "new_password2": self.NEW_PASSWORD,
        })
        # Coming back to set a second password must start over
        self.assertRedirects(
            self.client.get(reverse("accounts:password_reset_new")),
            reverse("accounts:password_reset"),
        )

    def test_a_verified_code_cannot_be_pointed_at_another_account(self):
        other = User.objects.create_user("09351234567", PASSWORD)
        other.mobile_verified = True
        other.save(update_fields=["mobile_verified"])

        with patch("accounts.otp.get_random_string", return_value="424242"):
            self.ask()
        self.client.post(reverse("accounts:password_reset_verify"), {"code": "424242"})

        session = self.client.session
        session["reset_mobile"] = other.mobile_number  # the proof was for a different number
        session.save()
        self.assertRedirects(
            self.client.get(reverse("accounts:password_reset_new")),
            reverse("accounts:password_reset"),
        )


class SignUpEmailTests(TestCase):
    def data(self, **changes):
        return {
            "mobile_number": "09121234567", "first_name": "علی", "last_name": "احمدی",
            "password1": PASSWORD, "password2": PASSWORD, **changes,
        }

    def test_email_is_optional(self):
        response = self.client.post(reverse("accounts:signup"), self.data())
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(User.objects.get().email)

    def test_an_email_that_is_given_is_kept_in_lower_case(self):
        self.client.post(reverse("accounts:signup"), self.data(email="  Ali@Example.COM "))
        self.assertEqual(User.objects.get().email, "ali@example.com")

    def test_the_same_email_cannot_be_used_twice(self):
        User.objects.create_user("09351234567", PASSWORD, email="ali@example.com")
        response = self.client.post(reverse("accounts:signup"), self.data(email="ALI@EXAMPLE.COM"))
        self.assertContains(response, "کاربری با این ایمیل وجود دارد")
        self.assertEqual(User.objects.count(), 1)

# --- Role label ---------------------------------------------------------------

class RoleLabelTests(TestCase):
    """One wording for one idea: the user list, the کارپوشه picker and the admin header agree."""

    def setUp(self):
        self.domain = Domain.objects.create(name="هوش مصنوعی", slug="ai")

    def test_a_domain_manager_is_named_after_their_group(self):
        user = User.objects.create_user("09121111111", PASSWORD, first_name="علی")
        user.groups.add(self.domain.group)
        self.assertEqual(role_label(user), "مدیران حوزه هوش مصنوعی")

    def test_a_superuser_is_the_system_owner_even_without_a_group(self):
        owner = User.objects.create_superuser("09122222222", PASSWORD, first_name="مالک")
        self.assertEqual(role_label(owner), "مالک سیستم")

    def test_someone_without_a_role_is_a_plain_customer(self):
        customer = User.objects.create_user("09123333333", PASSWORD, first_name="مشتری")
        self.assertEqual(role_label(customer), "کاربر عادی")

    def test_the_admin_header_shows_the_role(self):
        user = User.objects.create_user("09124444444", PASSWORD, first_name="علی")
        user.groups.add(self.domain.group)
        self.client.force_login(user)

        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, "مدیران حوزه هوش مصنوعی")
