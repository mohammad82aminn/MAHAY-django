"""
What a visitor sees when something goes wrong, and where the details go instead.
(Tests run with DEBUG off, as production does, so these are the real pages.)
"""
from django.contrib.auth.models import AnonymousUser
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import path, reverse
from django.views.debug import SafeExceptionReporterFilter

from accounts import views as account_views
from accounts.models import User

PASSWORD = "S3cure-pass!"


def boom(request):
    raise RuntimeError("secret detail of the failure")


# A urlconf with one failing page, for the 500 test (handlers are read from the urlconf in use)
urlpatterns = [path("boom/", boom)]
handler500 = "config.errors.server_error"


class ErrorPageTests(TestCase):
    def test_a_missing_page_shows_ours_and_nothing_about_the_site(self):
        with self.assertNumQueries(0):  # bots ask for these all day; they cost no query
            response = self.client.get("/no-such-place/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "صفحه پیدا نشد", status_code=404)
        for detail in ("no-such-place", "admin/", "urlpatterns", "Django"):
            self.assertNotContains(response, detail, status_code=404)

    def test_a_refused_page_shows_ours(self):
        owner = User.objects.create_superuser("09120000000", PASSWORD)
        self.client.force_login(owner)
        response = self.client.get(reverse("admin:accounts_user_deactivate", args=[owner.pk]))
        self.assertContains(response, "دسترسی ممکن نیست", status_code=403)

    @override_settings(ROOT_URLCONF=__name__)
    def test_a_failure_shows_ours_and_the_details_go_to_the_log(self):
        client = Client(raise_request_exception=False)
        with self.assertLogs("django.request", "ERROR") as logs:
            response = client.get("/boom/")
        self.assertContains(response, "مشکلی پیش آمد", status_code=500)
        self.assertNotContains(response, "secret detail", status_code=500)
        self.assertIn("secret detail of the failure", "\n".join(logs.output))

    def test_a_forged_host_gets_ours_and_is_logged(self):
        with self.assertLogs("django.security.DisallowedHost", "ERROR"):
            response = self.client.get("/", HTTP_HOST="evil.example")
        self.assertContains(response, "درخواست نامعتبر", status_code=400)

    def test_a_form_refused_by_the_csrf_check_explains_itself(self):
        client = Client(enforce_csrf_checks=True)
        with self.assertLogs("django.security.csrf", "WARNING"):
            response = client.post(reverse("accounts:login"), {"username": "x", "password": "y"})
        self.assertContains(response, "فرم ارسال نشد", status_code=403)
        self.assertNotContains(response, "CSRF", status_code=403)


class ErrorReportTests(TestCase):
    """A failure report (log file, email) must not carry a password or a one-time code."""

    def test_account_pages_hide_their_secrets_from_the_report(self):
        user = User.objects.create_user("09121111111", PASSWORD)
        pages = {
            account_views.SignUpView: ("password1", "password2"),
            account_views.VerifyView: ("code",),
            account_views.PasswordResetVerifyView: ("code",),
            account_views.PasswordResetNewView: ("new_password1", "new_password2"),
        }
        for view, fields in pages.items():
            with self.subTest(view=view.__name__):
                request = RequestFactory().post("/", {field: "plain-secret" for field in fields})
                request.user = user if view is account_views.SignUpView else AnonymousUser()
                request.session = {}
                view.as_view()(request)  # each one turns this visitor away; the marking happens first
                shown = SafeExceptionReporterFilter().get_post_parameters(request)
                for field in fields:
                    self.assertNotEqual(shown[field], "plain-secret")
