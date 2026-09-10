from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.test import TestCase
from .models import User

from .validators import normalize_mobile_number

CANONICAL = "+989121234567"


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


class UserManagerTests(TestCase):
    def test_create_user_normalizes_mobile_and_email(self):
        user = User.objects.create_user("۰۹۱۲ ۱۲۳ ۴۵۶۷", "S3cure-pass!", email=" Ali@Example.COM ")
        self.assertEqual(user.mobile_number, CANONICAL)
        self.assertEqual(user.email, "ali@example.com")
        self.assertTrue(user.check_password("S3cure-pass!"))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_same_number_in_other_format_is_duplicate(self):
        User.objects.create_user("09121234567", "S3cure-pass!")
        with self.assertRaises(ValidationError):
            User.objects.create_user("+989121234567", "S3cure-pass!")

    def test_invalid_mobile_rejected(self):
        with self.assertRaises(ValidationError):
            User.objects.create_user("abc", "S3cure-pass!")

    def test_users_without_email_do_not_collide(self):
        User.objects.create_user("09121234567", "S3cure-pass!", email="")
        user = User.objects.create_user("09351234567", "S3cure-pass!")
        self.assertIsNone(user.email)

    def test_email_unique_case_insensitive(self):
        User.objects.create_user("09121234567", "S3cure-pass!", email="a@b.com")
        with self.assertRaises(ValidationError):
            User.objects.create_user("09351234567", "S3cure-pass!", email="A@B.com")

    def test_create_superuser(self):
        admin = User.objects.create_superuser("09121234567", "S3cure-pass!")
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)


class LoginTests(TestCase):
    def setUp(self):
        User.objects.create_user("09121234567", "S3cure-pass!")

    def test_login_with_any_mobile_format(self):
        for value in ("09121234567", "+989121234567", "۰۹۱۲۱۲۳۴۵۶۷"):
            with self.subTest(value=value):
                self.assertIsNotNone(authenticate(username=value, password="S3cure-pass!"))

    def test_login_with_invalid_input_returns_none(self):
        self.assertIsNone(authenticate(username="abc", password="S3cure-pass!"))