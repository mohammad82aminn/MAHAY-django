"""
Sample lessons: ticked «قابل مشاهده بدون خرید», a lesson of a paid product opens its video and text
to everyone, so a visitor can try the course before buying it. Nothing else opens with it.
"""
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from approvals.models import ChangeRequest
from commerce.models import Purchase
from products.models import Product

from .models import Attachment, Lesson, Section
from .tests import APARAT, ContentTestCase, video


class SampleLessonTestCase(ContentTestCase):
    def setUp(self):
        super().setUp()
        self.sample = Lesson.objects.create(section=self.section, title="درس نمونه", video_file=video(),
                                            is_published=True, is_free_preview=True, order=1)
        self.paid = Lesson.objects.create(section=self.section, title="درس پولی", video_file=video(),
                                          is_published=True, order=2)
        self.handout = Attachment.objects.create(lesson=self.sample, title="جزوه‌ی درس نمونه", is_published=True,
                                                 file=SimpleUploadedFile("handout.pdf", b"%PDF-1.4"))

    def sample_url(self, lesson):
        return reverse("content:sample", args=[self.product.slug, lesson.pk])

    def video_url(self, lesson):
        return reverse("content:protected_file", args=["video", lesson.pk])

    def handout_url(self):
        return reverse("content:protected_file", args=["attachment", self.handout.pk])


class WatchingASampleTests(SampleLessonTestCase):
    def test_the_product_page_links_the_sample_and_locks_the_rest(self):
        page = self.client.get(self.product.get_absolute_url())
        self.assertContains(page, self.sample_url(self.sample))
        self.assertContains(page, "رایگان ببینید")
        self.assertContains(page, "🔒 درس پولی")
        self.assertNotContains(page, self.sample_url(self.paid))

    def test_anyone_can_watch_it_without_logging_in(self):
        page = self.client.get(self.sample_url(self.sample))
        self.assertContains(page, self.video_url(self.sample))
        self.assertContains(page, reverse("commerce:add_to_cart", args=[self.product.slug]))
        self.assertNotContains(page, "جزوه‌ی درس نمونه")  # the attachments are the buyers'
        self.assertEqual(self.client.get(self.video_url(self.sample)).status_code, 200)

    def test_the_rest_stays_closed(self):
        self.assertEqual(self.client.get(self.sample_url(self.paid)).status_code, 404)
        for url in (self.video_url(self.paid), self.handout_url()):
            with self.subTest(url=url, who="visitor"):
                self.assertIn(reverse("accounts:login"), self.client.get(url)["Location"])

        self.client.force_login(self.other_manager)  # logged in, bought nothing here
        for url in (self.video_url(self.paid), self.handout_url()):
            with self.subTest(url=url, who="stranger"):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_a_missing_file_looks_the_same_as_a_closed_one(self):
        missing = reverse("content:protected_file", args=["video", 999_999])
        self.assertIn(reverse("accounts:login"), self.client.get(missing)["Location"])

    def test_a_buyer_goes_to_the_full_lesson_page(self):
        Purchase.objects.create(user=self.buyer, product=self.product)
        self.client.force_login(self.buyer)
        self.assertRedirects(self.client.get(self.sample_url(self.sample)),
                             reverse("content:lesson", args=[self.product.slug, self.sample.pk]))

    def test_the_page_moves_between_the_samples_only(self):
        later = Lesson.objects.create(section=self.section, title="نمونه‌ی دوم", body="متن", is_published=True,
                                      is_free_preview=True, order=3)
        page = self.client.get(self.sample_url(self.sample))
        self.assertContains(page, self.sample_url(later))
        self.assertNotContains(page, self.sample_url(self.paid))


class OnlyALiveSampleOpensTests(SampleLessonTestCase):
    """Ticked is not enough: the lesson must be on show, in a paid product that is in the store."""

    def assert_closed(self):
        self.assertEqual(self.client.get(self.sample_url(self.sample)).status_code, 404)
        self.assertIn(reverse("accounts:login"), self.client.get(self.video_url(self.sample))["Location"])

    def test_not_yet_approved(self):
        Lesson.objects.filter(pk=self.sample.pk).update(is_published=False)
        self.assert_closed()

    def test_removed(self):
        Lesson.objects.filter(pk=self.sample.pk).update(is_archived=True)
        self.assert_closed()

    def test_its_section_not_on_show(self):
        Section.objects.filter(pk=self.section.pk).update(is_published=False)
        self.assert_closed()

    def test_the_product_not_in_the_store(self):
        Product.objects.filter(pk=self.product.pk).update(is_published=False)
        self.assert_closed()

    def test_a_free_product_has_no_samples(self):
        # ordered for nothing and opened whole, as before
        Product.objects.filter(pk=self.product.pk).update(price=0)
        self.assert_closed()
        self.assertNotContains(self.client.get(self.product.get_absolute_url()), "رایگان ببینید")


class SettingASampleTests(SampleLessonTestCase):
    def test_a_sample_may_be_an_aparat_video_in_a_paid_product(self):
        Lesson(section=self.section, title="x", video_url=APARAT, is_free_preview=True).full_clean()
        with self.assertRaises(ValidationError):
            Lesson(section=self.section, title="x", video_url=APARAT).full_clean()

    def test_aparat_samples_do_not_stop_a_product_from_being_paid(self):
        Lesson.objects.create(section=self.section, title="نمونه‌ی آپاراتی", video_url=APARAT, is_free_preview=True)
        self.product.full_clean()

    def test_a_managers_tick_waits_for_approval(self):
        self.client.force_login(self.manager)
        self.client.post(reverse("admin:content_lesson_change", args=[self.paid.pk]), {
            "section": self.section.pk, "title": "درس پولی", "order": 2, "body": "", "video_url": "",
            "duration_minutes": "", "is_free_preview": "on",
        })
        self.paid.refresh_from_db()
        self.assertFalse(self.paid.is_free_preview)
        self.assertIs(ChangeRequest.objects.get(action="update").data["is_free_preview"], True)

        self.client.logout()
        self.assertEqual(self.client.get(self.sample_url(self.paid)).status_code, 404)

    def test_no_tick_for_a_lesson_of_a_free_product(self):
        self.client.force_login(self.admin)
        url = reverse("admin:content_lesson_change", args=[self.paid.pk])
        self.assertIn("is_free_preview", self.client.get(url).context["adminform"].form.fields)
        Product.objects.filter(pk=self.product.pk).update(price=0)
        self.assertNotIn("is_free_preview", self.client.get(url).context["adminform"].form.fields)
