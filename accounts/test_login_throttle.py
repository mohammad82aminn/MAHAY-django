from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import throttle
from .models import LoginAttempt, User

PASSWORD = "S3cure-pass!"


class LoginThrottleTests(TestCase):
    url = reverse("accounts:login")

    def setUp(self):
        self.user = User.objects.create_user("09121234567", PASSWORD, first_name="علی")

    def attempt(self, password="wrong-pass", number="09121234567"):
        return self.client.post(self.url, {"username": number, "password": password})

    def test_wrong_password_is_recorded(self):
        self.attempt()
        self.assertEqual(LoginAttempt.objects.count(), 1)
        self.assertEqual(LoginAttempt.objects.get().mobile_number, "+989121234567")

    def test_login_is_blocked_after_five_failures(self):
        for _ in range(throttle.MAX_PER_NUMBER):
            self.attempt()
        response = self.attempt(password=PASSWORD)  # even the right password must wait
        self.assertContains(response, "دقیقه دیگر دوباره تلاش کنید")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_block_expires(self):
        for _ in range(throttle.MAX_PER_NUMBER):
            self.attempt()
        LoginAttempt.objects.update(created_at=timezone.now() - throttle.WINDOW - timedelta(minutes=1))
        self.attempt(password=PASSWORD)
        self.assertIn("_auth_user_id", self.client.session)

    def test_successful_login_clears_the_failures(self):
        self.attempt()
        self.attempt()
        self.attempt(password=PASSWORD)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertFalse(LoginAttempt.objects.filter(mobile_number="+989121234567").exists())

    def test_another_number_is_not_blocked(self):
        other = User.objects.create_user("09351234567", PASSWORD)
        for _ in range(throttle.MAX_PER_NUMBER):
            self.attempt()
        response = self.client.post(self.url, {"username": other.mobile_number, "password": PASSWORD})
        self.assertEqual(response.status_code, 302)  # logged in

    def test_spraying_many_accounts_from_one_ip_is_blocked(self):
        for index in range(throttle.MAX_PER_IP):
            self.attempt(number=f"0912000{index:04d}")
        response = self.attempt(password=PASSWORD)
        self.assertContains(response, "دقیقه دیگر دوباره تلاش کنید")

    def test_forged_proxy_header_is_ignored(self):
        # Nothing in front of us, so the header is the visitor's own words: it must not count.
        self.client.post(self.url, {"username": "09121234567", "password": "x"},
                         HTTP_X_FORWARDED_FOR="5.6.7.8")
        self.assertEqual(LoginAttempt.objects.get().ip_address, "127.0.0.1")

    def test_proxy_header_is_used_behind_our_own_proxy(self):
        # nginx appends the address it saw, so the last entry is the real visitor
        # and the "5.6.7.8" in front of it is what that visitor tried to pretend.
        with self.settings(TRUSTED_PROXIES=["127.0.0.1"]):
            self.client.post(self.url, {"username": "09121234567", "password": "x"},
                             HTTP_X_FORWARDED_FOR="5.6.7.8, 10.0.0.1")
        self.assertEqual(LoginAttempt.objects.get().ip_address, "10.0.0.1")