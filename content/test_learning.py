import shutil
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from commerce.models import Purchase
from domains.models import Domain
from products.models import Product

from .models import Attachment, Lesson, LessonProgress, Section
from .testing import mp4_upload

PASSWORD = "S3cure-pass!"
TEMP_PROTECTED = tempfile.mkdtemp()
APARAT = "https://www.aparat.com/v/abc123"


def video(name="v.mp4"):
    return mp4_upload(name, seconds=600)


@override_settings(PROTECTED_MEDIA_ROOT=TEMP_PROTECTED)
class LearningTestCase(TestCase):
    def setUp(self):
        self.domain = Domain.objects.create(name="FPGA", slug="fpga")
        self.product = Product.objects.create(
            product_type="course", title="دوره FPGA", slug="fpga", primary_domain=self.domain,
            price=500_000, is_published=True, cover="products/covers/c.png",
        )
        self.section = Section.objects.create(product=self.product, title="فصل ۱", is_published=True)
        self.lesson1 = Lesson.objects.create(section=self.section, title="درس یک", is_published=True,
                                             video_file=video(), order=1)
        self.lesson2 = Lesson.objects.create(section=self.section, title="درس دو", is_published=True,
                                             body="متن درس", order=2)
        self.hidden = Lesson.objects.create(section=self.section, title="درس منتظر تأیید", order=3)

        self.buyer = User.objects.create_user("09121111111", PASSWORD)
        Purchase.objects.create(user=self.buyer, product=self.product)
        self.stranger = User.objects.create_user("09122222222", PASSWORD)

    def learn_url(self):
        return reverse("content:learn", args=[self.product.slug])

    def lesson_url(self, lesson):
        return reverse("content:lesson", args=[self.product.slug, lesson.pk])


class AccessTests(LearningTestCase):
    def test_only_buyers_can_open_the_course(self):
        self.assertIn(reverse("accounts:login"), self.client.get(self.learn_url())["Location"])

        self.client.force_login(self.stranger)
        self.assertRedirects(self.client.get(self.learn_url()), self.product.get_absolute_url())
        self.assertRedirects(self.client.get(self.lesson_url(self.lesson1)), self.product.get_absolute_url())

        self.client.force_login(self.buyer)
        self.assertContains(self.client.get(self.learn_url()), "دوره FPGA")

    def test_a_product_outside_the_store_looks_missing_to_a_stranger(self):
        # A redirect to its page would tell them the address belongs to an unpublished product
        Product.objects.filter(pk=self.product.pk).update(is_published=False)
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.learn_url()).status_code, 404)
        self.assertEqual(self.client.get(self.lesson_url(self.lesson1)).status_code, 404)

        self.client.force_login(self.buyer)  # what they bought stays theirs
        self.assertEqual(self.client.get(self.learn_url()).status_code, 200)

    def test_domain_manager_can_review_the_content(self):
        manager = User.objects.create_user("09123333333", PASSWORD)
        manager.groups.add(self.domain.managers_group)
        self.client.force_login(manager)
        self.assertEqual(self.client.get(self.learn_url()).status_code, 200)

    def test_unapproved_lessons_are_not_shown(self):
        self.client.force_login(self.buyer)
        response = self.client.get(self.learn_url())
        self.assertContains(response, "درس یک")
        self.assertNotContains(response, "درس منتظر تأیید")
        self.assertEqual(self.client.get(self.lesson_url(self.hidden)).status_code, 404)


class LessonPageTests(LearningTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.buyer)

    def test_video_lesson_shows_the_player(self):
        response = self.client.get(self.lesson_url(self.lesson1))
        self.assertContains(response, reverse("content:protected_file", args=["video", self.lesson1.pk]))
        self.assertContains(response, "درس بعدی")

    def test_text_lesson_is_completed_by_opening_it(self):
        self.client.get(self.lesson_url(self.lesson2))
        row = LessonProgress.objects.get(user=self.buyer, lesson=self.lesson2)
        self.assertTrue(row.is_completed)

    def test_video_lesson_is_not_completed_by_opening_it(self):
        self.client.get(self.lesson_url(self.lesson1))
        self.assertFalse(LessonProgress.objects.get(user=self.buyer, lesson=self.lesson1).is_completed)

    def test_attachments_are_listed(self):
        Attachment.objects.create(lesson=self.lesson1, title="جزوه", file="attachments/a.pdf", is_published=True)
        self.assertContains(self.client.get(self.lesson_url(self.lesson1)), "جزوه")

    def test_thesis_is_offered_on_the_course_page(self):
        self.product.product_type = "project"
        self.product.thesis = "thesis/t.pdf"
        self.product.save()
        self.assertContains(self.client.get(self.learn_url()), "دانلود پایان‌نامه")


class ProgressTests(LearningTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.buyer)
        self.save_url = reverse("content:save_progress", args=[self.lesson1.pk])

    def save(self, position, duration=600):
        return self.client.post(self.save_url, {"position": position, "duration": duration})

    def test_percent_is_saved_while_watching(self):
        response = self.save(150)  # 150 of 600 seconds
        self.assertEqual(response.json(), {"percent": 25, "completed": False})
        row = LessonProgress.objects.get(user=self.buyer, lesson=self.lesson1)
        self.assertEqual(row.position_seconds, 150)

    def test_ninety_percent_completes_the_lesson(self):
        self.assertTrue(self.save(540).json()["completed"])  # 540 / 600 = 90%
        self.assertEqual(self.save(540).json()["percent"], 100)

    def test_completion_is_never_taken_back(self):
        self.save(600)
        self.save(5)  # the user starts watching again from the beginning
        row = LessonProgress.objects.get(user=self.buyer, lesson=self.lesson1)
        self.assertTrue(row.is_completed)
        self.assertEqual(row.position_seconds, 5)  # but it still resumes from there

    def test_lesson_page_resumes_from_the_saved_position(self):
        self.save(200)
        self.assertEqual(self.client.get(self.lesson_url(self.lesson1)).context["position"], 200)

    def test_course_percent_and_next_lesson(self):
        response = self.client.get(self.learn_url())
        self.assertEqual(response.context["percent"], 0)
        self.assertEqual(response.context["total"], 2)  # the unapproved lesson doesn't count
        self.assertEqual(response.context["next_lesson"], self.lesson1)

        self.save(600)  # finish the first lesson
        response = self.client.get(self.learn_url())
        self.assertEqual(response.context["percent"], 50)
        self.assertEqual(response.context["next_lesson"], self.lesson2)
        self.assertContains(response, "ادامه‌ی یادگیری")

    def test_percent_is_shown_in_the_lesson_list(self):
        self.save(180)  # 30%
        self.assertContains(self.client.get(self.learn_url()), "۳۰٪ دیده‌شده")

    def test_strangers_cannot_save_progress(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.save(100).status_code, 404)

    def test_invalid_numbers_are_refused(self):
        self.assertEqual(self.client.post(self.save_url, {"position": "x", "duration": "y"}).status_code, 400)


class LibraryProgressTests(LearningTestCase):
    def test_library_shows_progress_and_continue_button(self):
        self.client.force_login(self.buyer)
        self.client.post(reverse("content:save_progress", args=[self.lesson1.pk]), {"position": 600, "duration": 600})
        response = self.client.get(reverse("commerce:library"))
        self.assertContains(response, "۵۰٪")
        self.assertContains(response, "ادامه‌ی یادگیری")
        self.assertContains(response, reverse("content:lesson", args=[self.product.slug, self.lesson2.pk]))


def tearDownModule():
    shutil.rmtree(TEMP_PROTECTED, ignore_errors=True)