from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import otp
from .models import User, VerificationCode

PASSWORD = "S3cure-pass!"
SIGNUP_DATA = {
    "mobile_number": "09121234567", "first_name": "علی", "last_name": "رضایی",
    "password1": PASSWORD, "password2": PASSWORD,
}


@override_settings(SMS_BACKEND="console", DEBUG=False)
class SignUpVerificationTests(TestCase):
    signup_url = reverse("accounts:signup")
    verify_url = reverse("accounts:verify")

    def signup(self, **changes):
        return self.client.post(self.signup_url, {**SIGNUP_DATA, **changes})

    def signup_and_get_code(self):
        with self.assertLogs("accounts.sms", level="INFO") as logs:
            self.signup()
        return logs.output[0].split(": ")[-1]

    def test_signup_creates_an_inactive_user_and_sends_a_code(self):
        response = self.signup()
        self.assertRedirects(response, self.verify_url)

        user = User.objects.get()
        self.assertFalse(user.is_active)
        self.assertFalse(user.mobile_verified)
        self.assertEqual(VerificationCode.objects.count(), 1)
        self.assertNotIn("_auth_user_id", self.client.session)  # not logged in yet

    def test_right_code_activates_the_account_and_logs_in(self):
        code = self.signup_and_get_code()
        response = self.client.post(self.verify_url, {"code": code})
        self.assertRedirects(response, reverse("home"))

        user = User.objects.get()
        self.assertTrue(user.is_active)
        self.assertTrue(user.mobile_verified)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_persian_digits_are_accepted(self):
        code = self.signup_and_get_code()
        persian = code.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
        self.assertRedirects(self.client.post(self.verify_url, {"code": persian}), reverse("home"))

    def test_wrong_code_is_refused(self):
        self.signup_and_get_code()
        response = self.client.post(self.verify_url, {"code": "000000"})
        self.assertContains(response, "نادرست یا منقضی")
        self.assertFalse(User.objects.get().is_active)

    def test_code_dies_after_five_wrong_tries(self):
        code = self.signup_and_get_code()
        for _ in range(otp.MAX_ATTEMPTS):
            self.client.post(self.verify_url, {"code": "000000"})
        response = self.client.post(self.verify_url, {"code": code})  # the real code, but too late
        self.assertContains(response, "نادرست یا منقضی")
        self.assertFalse(User.objects.get().is_active)

    def test_expired_code_is_refused(self):
        code = self.signup_and_get_code()
        VerificationCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertContains(self.client.post(self.verify_url, {"code": code}), "نادرست یا منقضی")

    def test_verify_page_needs_a_pending_signup(self):
        self.assertRedirects(self.client.get(self.verify_url), self.signup_url)

    def test_resend_is_blocked_for_a_while(self):
        self.signup()
        response = self.client.post(reverse("accounts:resend_code"), follow=True)
        self.assertContains(response, "ثانیه صبر کنید")
        self.assertEqual(VerificationCode.objects.count(), 1)

    def test_resend_replaces_the_old_code(self):
        old = self.signup_and_get_code()
        VerificationCode.objects.update(created_at=timezone.now() - otp.RESEND_AFTER)
        self.client.post(reverse("accounts:resend_code"))
        self.assertEqual(VerificationCode.objects.count(), 2)
        self.assertContains(self.client.post(self.verify_url, {"code": old}), "نادرست یا منقضی")

    def test_hourly_limit_protects_the_sms_credit(self):
        self.signup()
        for _ in range(otp.MAX_PER_HOUR):
            VerificationCode.objects.update(created_at=timezone.now() - otp.RESEND_AFTER)
            self.client.post(reverse("accounts:resend_code"))
        response = self.client.post(reverse("accounts:resend_code"), follow=True)
        self.assertContains(response, "یک ساعت دیگر")

    def test_unverified_number_can_sign_up_again(self):
        self.signup()
        response = self.signup(first_name="رضا")  # same number, second try
        self.assertRedirects(response, self.verify_url)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(User.objects.get().first_name, "رضا")

    def test_verified_number_cannot_be_taken(self):
        code = self.signup_and_get_code()
        self.client.post(self.verify_url, {"code": code})
        self.client.logout()
        response = self.signup()
        self.assertContains(response, "وجود دارد")
        self.assertEqual(User.objects.count(), 1)

    def test_unverified_user_cannot_log_in(self):
        self.signup()
        response = self.client.post(reverse("accounts:login"), {"username": "09121234567", "password": PASSWORD})
        self.assertContains(response, "تأیید نشده")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_code_is_not_stored_in_plain_text(self):
        code = self.signup_and_get_code()
        self.assertNotIn(code, VerificationCode.objects.get().code_hash)

    @override_settings(DEBUG=True)
    def test_code_is_shown_on_screen_only_in_development(self):
        response = self.client.post(self.signup_url, SIGNUP_DATA, follow=True)
        self.assertContains(response, "حالت آزمایشی")

    def test_code_is_not_shown_on_screen_in_production(self):
        response = self.client.post(self.signup_url, SIGNUP_DATA, follow=True)
        self.assertNotContains(response, "حالت آزمایشی")


@override_settings(SMS_BACKEND="disabled")
class SignUpWithoutSmsTests(TestCase):
    def test_signup_stays_one_step_when_sms_is_off(self):
        response = self.client.post(reverse("accounts:signup"), SIGNUP_DATA)
        self.assertRedirects(response, reverse("home"))
        user = User.objects.get()
        self.assertTrue(user.is_active)
        self.assertFalse(user.mobile_verified)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertFalse(VerificationCode.objects.exists())