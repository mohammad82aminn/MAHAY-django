"""
Applying to work with MAHAY.

Two things are being protected: somebody's documents, which belong to them and to whoever is
allowed to review applications and to nobody else; and the reviewer's reading, which must not
change underneath them once they have started.
"""
import shutil
import tempfile

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from accounts.roles import SITE_ADMINS_GROUP
from domains.models import Domain

from . import services
from .models import CollaborationRequest
from .validators import MAX_FILES

PASSWORD = "S3cure-pass!"
TEMP_PROTECTED = tempfile.mkdtemp()
PITCH = "چند سال با FPGA کار کرده‌ام و می‌توانم برایتان دوره بسازم."


@override_settings(PROTECTED_MEDIA_ROOT=TEMP_PROTECTED)
class CollaborationTestCase(TestCase):
    def setUp(self):
        self.fpga = Domain.objects.create(name="FPGA", slug="fpga")
        self.applicant = User.objects.create_user("09121234567", PASSWORD, first_name="رضا", last_name="م")
        self.other = User.objects.create_user("09122222222", PASSWORD, first_name="سارا")

        self.reviewer = User.objects.create_user("09120000000", PASSWORD, first_name="مدیر")
        self.reviewer.groups.add(Group.objects.get(name=SITE_ADMINS_GROUP))
        self.reviewer.refresh_from_db()  # is_staff is set by a signal through a queryset update

        self.expert = User.objects.create_user("09121111111", PASSWORD, first_name="علی")
        self.expert.groups.add(self.fpga.group)
        self.expert.refresh_from_db()

        self.url = reverse("collaboration:apply")

    def form_data(self, **changes):
        data = {
            "contact_channel": "telegram", "contact_id": "@reza", "pitch": PITCH,
            "work": ["teach"], "domains": [self.fpga.pk], "degree": "master",
            "field_of_study": "برق", "experience": "", "skills": "", "links": "", "other_domain": "",
        }
        data.update(changes)
        return data

    def apply_as(self, user, **changes):
        self.client.force_login(user)
        return self.client.post(self.url, self.form_data(**changes))

    @staticmethod
    def pdf(name="cv.pdf"):
        return SimpleUploadedFile(name, b"%PDF-1.4", content_type="application/pdf")


class WhoMayApplyTests(CollaborationTestCase):
    def test_a_visitor_is_sent_to_sign_in(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_somebody_with_an_account_may_apply(self):
        self.client.force_login(self.applicant)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertTrue(services.may_apply(self.applicant))

    def test_somebody_who_already_works_here_is_not_offered_it(self):
        # Inviting a domain manager to apply for collaboration would be an odd thing to say
        self.client.force_login(self.expert)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertFalse(services.may_apply(self.expert))

    def test_the_menu_link_follows_the_same_rule(self):
        for user, shown in ((self.applicant, True), (self.expert, False)):
            with self.subTest(user=user.first_name):
                self.client.force_login(user)
                body = self.client.get(reverse("home")).content.decode()
                self.assertIs("collaboration/apply" in body, shown)


class ApplyingTests(CollaborationTestCase):
    def test_an_application_is_recorded_against_the_account(self):
        self.apply_as(self.applicant)
        application = CollaborationRequest.objects.get()

        self.assertEqual(application.user, self.applicant)
        self.assertEqual(application.status, CollaborationRequest.Status.NEW)
        self.assertTrue(application.can_teach)
        self.assertEqual(list(application.domains.all()), [self.fpga])

    def test_several_files_may_be_sent(self):
        self.client.force_login(self.applicant)
        self.client.post(self.url, {**self.form_data(), "files": [self.pdf("cv.pdf"), self.pdf("work.pdf")]})
        self.assertEqual(CollaborationRequest.objects.get().files.count(), 2)

    def test_too_many_files_are_refused(self):
        self.client.force_login(self.applicant)
        response = self.client.post(self.url, {
            **self.form_data(), "files": [self.pdf(f"cv{i}.pdf") for i in range(MAX_FILES + 1)],
        })
        self.assertContains(response, "حداکثر")
        self.assertFalse(CollaborationRequest.objects.exists())

    def test_a_second_submission_updates_the_open_one(self):
        self.apply_as(self.applicant)
        self.apply_as(self.applicant, pitch="متن تازه‌ای که به‌جای قبلی می‌نشیند و کوتاه هم نیست.")

        self.assertEqual(CollaborationRequest.objects.count(), 1)
        self.assertIn("متن تازه", CollaborationRequest.objects.get().pitch)

    def test_an_application_that_says_nothing_is_refused(self):
        response = self.apply_as(self.applicant, pitch="سلام")
        self.assertContains(response, "کمی بیشتر بنویسید")
        self.assertFalse(CollaborationRequest.objects.exists())

    def test_a_way_to_reach_them_is_required(self):
        response = self.apply_as(self.applicant, contact_id="")
        self.assertContains(response, "آیدی خود را")
        self.assertFalse(CollaborationRequest.objects.exists())

    def test_at_least_one_kind_of_work_is_required(self):
        response = self.apply_as(self.applicant, work=[])
        self.assertContains(response, "دست‌کم یک نوع همکاری")
        self.assertFalse(CollaborationRequest.objects.exists())


class ReviewingTests(CollaborationTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.applicant)
        self.client.post(self.url, {**self.form_data(), "files": [self.pdf()]})
        self.application = CollaborationRequest.objects.get()

    def test_it_can_be_corrected_until_somebody_starts_reading(self):
        self.assertTrue(self.application.is_editable)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_it_freezes_once_it_is_being_reviewed(self):
        # Otherwise what the reviewer is reading could change underneath them
        self.application.mark_reviewed(CollaborationRequest.Status.REVIEWING, self.reviewer)
        self.assertFalse(self.application.is_editable)
        self.assertRedirects(self.client.get(self.url), reverse("services:my_requests"))

    def test_rejecting_drops_the_documents_but_keeps_the_record(self):
        self.application.mark_reviewed(CollaborationRequest.Status.REJECTED, self.reviewer)
        self.application.refresh_from_db()

        self.assertEqual(self.application.files.count(), 0)
        self.assertTrue(self.application.pitch)
        self.assertEqual(self.application.reviewed_by, self.reviewer)

    def test_accepting_keeps_the_documents(self):
        self.application.mark_reviewed(CollaborationRequest.Status.ACCEPTED, self.reviewer)
        self.assertEqual(self.application.files.count(), 1)

    def test_a_closed_application_lets_them_try_again(self):
        self.application.mark_reviewed(CollaborationRequest.Status.REJECTED, self.reviewer)
        self.assertIsNone(services.open_request(self.applicant))

        self.client.post(self.url, self.form_data(pitch="این بار کامل‌تر نوشته‌ام و تجربه‌ی تازه دارم."))
        self.assertEqual(CollaborationRequest.objects.filter(user=self.applicant).count(), 2)

    def test_the_applicant_sees_the_status_in_their_requests(self):
        self.application.mark_reviewed(CollaborationRequest.Status.REVIEWING, self.reviewer)
        response = self.client.get(reverse("services:my_requests"))
        self.assertContains(response, "در حال بررسی")


class FileAccessTests(CollaborationTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.applicant)
        self.client.post(self.url, {**self.form_data(), "files": [self.pdf()]})
        self.file = CollaborationRequest.objects.get().files.first()
        self.file_url = reverse("collaboration:file", args=[self.file.pk])

    def test_the_applicant_may_read_their_own_file(self):
        self.assertEqual(self.client.get(self.file_url).status_code, 200)

    def test_a_reviewer_may_read_it(self):
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(self.file_url).status_code, 200)

    def test_nobody_else_may(self):
        # 404 rather than 403: not even the existence of somebody's CV is anybody's business
        for user in (self.other, self.expert):
            with self.subTest(user=user.first_name):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.file_url).status_code, 404)


def tearDownModule():
    shutil.rmtree(TEMP_PROTECTED, ignore_errors=True)
