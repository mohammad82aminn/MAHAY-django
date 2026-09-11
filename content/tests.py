import shutil
import tempfile
from pathlib import Path

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from accounts.roles import SITE_ADMINS_GROUP
from approvals.models import ChangeRequest
from domains.models import Domain
from products.models import Product

from .models import Attachment, Lesson, Section

PASSWORD = "S3cure-pass!"
TEMP_PROTECTED = tempfile.mkdtemp()
TEMP_MEDIA = tempfile.mkdtemp()
APARAT = "https://www.aparat.com/v/abc123"
GIF = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"


def video(name="lesson.mp4"):
    return SimpleUploadedFile(name, b"fake video bytes", content_type="video/mp4")


@override_settings(PROTECTED_MEDIA_ROOT=TEMP_PROTECTED, MEDIA_ROOT=TEMP_MEDIA)
class ContentTestCase(TestCase):
    def setUp(self):
        self.fpga = Domain.objects.create(name="FPGA", slug="fpga")
        self.ai = Domain.objects.create(name="هوش مصنوعی", slug="ai")
        self.manager = User.objects.create_user("09121111111", PASSWORD)
        self.manager.groups.add(self.fpga.group)
        self.other_manager = User.objects.create_user("09123333333", PASSWORD)
        self.other_manager.groups.add(self.ai.group)
        self.admin = User.objects.create_user("09122222222", PASSWORD)
        self.admin.groups.add(Group.objects.get(name=SITE_ADMINS_GROUP))
        self.buyer = User.objects.create_user("09124444444", PASSWORD)

        self.product = Product.objects.create(
            product_type="course", title="مبانی FPGA", slug="fpga-basics", primary_domain=self.fpga,
            price=1_000_000, is_published=True, cover="products/covers/test.png",
        )
        self.section = Section.objects.create(product=self.product, title="فصل ۱", is_published=True)

    def lesson_with_video(self):
        return Lesson.objects.create(section=self.section, title="درس ۱", video_file=video(), is_published=True)


class ProtectedFileTests(ContentTestCase):
    def test_paid_video_is_not_in_public_media(self):
        lesson = self.lesson_with_video()
        name = str(lesson.video_file.name)
        self.assertTrue((Path(TEMP_PROTECTED) / name).exists())
        self.assertFalse((Path(TEMP_MEDIA) / name).exists())
        self.assertEqual(lesson.video_file.url, "#")  # no direct link

    def test_who_can_open_a_paid_video(self):
        url = reverse("content:protected_file", args=["video", self.lesson_with_video().pk])
        self.assertEqual(self.client.get(url).status_code, 302)  # anonymous -> login page
        for user, status in ((self.buyer, 404), (self.other_manager, 404), (self.manager, 200), (self.admin, 200)):
            with self.subTest(user=user.mobile_number):
                self.client.force_login(user)
                self.assertEqual(self.client.get(url).status_code, status)


class LessonValidationTests(ContentTestCase):
    def test_only_aparat_links(self):
        lesson = Lesson(section=self.section, title="x", video_url="https://youtube.com/watch?v=1")
        with self.assertRaises(ValidationError):
            lesson.full_clean()

    def test_aparat_not_allowed_for_paid_product(self):
        with self.assertRaises(ValidationError):
            Lesson(section=self.section, title="x", video_url=APARAT).full_clean()

    def test_aparat_allowed_for_free_product(self):
        self.product.price = 0
        self.product.save()
        Lesson(section=self.section, title="x", video_url=APARAT).full_clean()

    def test_file_and_link_together_not_allowed(self):
        self.product.price = 0
        self.product.save()
        with self.assertRaises(ValidationError):
            Lesson(section=self.section, title="x", video_url=APARAT, video_file="videos/a.mp4").full_clean()


class ManagerContentTests(ContentTestCase):
    def test_new_section_waits_for_approval(self):
        self.client.force_login(self.manager)
        self.client.post(reverse("admin:content_section_add"), {"product": self.product.pk, "title": "فصل ۲", "order": 2})
        section = Section.objects.get(title="فصل ۲")
        self.assertFalse(section.is_published)
        self.assertTrue(ChangeRequest.objects.filter(action="create", object_id=section.pk, domain=self.fpga).exists())

    def test_manager_cannot_add_to_other_domain_product(self):
        ai_product = Product.objects.create(product_type="course", title="AI", slug="ai", primary_domain=self.ai)
        self.client.force_login(self.manager)
        response = self.client.post(reverse("admin:content_section_add"), {"product": ai_product.pk, "title": "x", "order": 0})
        self.assertEqual(response.status_code, 200)  # form error
        self.assertFalse(Section.objects.filter(title="x").exists())

    def test_manager_sees_only_own_lessons(self):
        own = self.lesson_with_video()
        ai_product = Product.objects.create(product_type="course", title="AI", slug="ai", primary_domain=self.ai)
        Lesson.objects.create(section=Section.objects.create(product=ai_product, title="s"), title="other")
        self.client.force_login(self.manager)
        response = self.client.get(reverse("admin:content_lesson_changelist"))
        self.assertEqual(list(response.context["cl"].queryset), [own])

    def test_new_video_of_published_lesson_waits_in_protected_storage(self):
        lesson = self.lesson_with_video()
        old_name = lesson.video_file.name
        self.client.force_login(self.manager)
        self.client.post(reverse("admin:content_lesson_change", args=[lesson.pk]), {
            "section": self.section.pk, "title": "درس ۱", "order": 0, "body": "", "video_url": "",
            "video_file": video("new.mp4"),
        })
        lesson.refresh_from_db()
        self.assertEqual(lesson.video_file.name, old_name)  # buyers still get the old video

        request = ChangeRequest.objects.get(action="update")
        pending_name = request.data["video_file"]
        self.assertTrue((Path(TEMP_PROTECTED) / pending_name).exists())
        self.assertFalse((Path(TEMP_MEDIA) / pending_name).exists())

        pending_url = reverse("approvals:pending_file", args=[request.pk, "video_file"])
        self.client.force_login(self.buyer)
        self.assertNotEqual(self.client.get(pending_url).status_code, 200)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(pending_url).status_code, 200)

        self.client.post(reverse("admin:approvals_changerequest_change", args=[request.pk]), {"status": "approved"})
        lesson.refresh_from_db()
        self.assertEqual(lesson.video_file.name, pending_name)


class PublishTogetherTests(ContentTestCase):
    def test_approving_new_product_publishes_its_new_content(self):
        self.client.force_login(self.manager)
        self.client.post(reverse("admin:products_product_add"), {
            "product_type": "project", "title": "ربات", "slug": "robot", "summary": "", "description": "",
            "intro_video_url": "", "primary_domain": self.fpga.pk, "price": 0, "sale_price": "",
            "cover": SimpleUploadedFile("cover.gif", GIF, content_type="image/gif"),
        })
        product = Product.objects.get(slug="robot")
        self.client.post(reverse("admin:content_section_add"), {"product": product.pk, "title": "معرفی", "order": 0})
        section = Section.objects.get(title="معرفی")
        self.client.post(reverse("admin:content_lesson_add"), {
            "section": section.pk, "title": "توضیح پروژه", "order": 0, "body": "", "video_url": APARAT,
        })
        lesson = Lesson.objects.get(title="توضیح پروژه")
        self.client.post(reverse("admin:content_attachment_add"), {
            "lesson": lesson.pk, "title": "README", "order": 0, "file": SimpleUploadedFile("README.md", b"# robot"),
        })
        attachment = Attachment.objects.get(title="README")
        self.assertEqual(ChangeRequest.objects.filter(status="pending").count(), 4)

        product_request = ChangeRequest.objects.get(action="create", object_id=product.pk, content_type__model="product")
        self.client.force_login(self.admin)
        self.client.post(reverse("admin:approvals_changerequest_change", args=[product_request.pk]), {"status": "approved"})

        for obj in (product, section, lesson, attachment):
            obj.refresh_from_db()
            self.assertTrue(obj.is_published, obj)
        self.assertFalse(ChangeRequest.objects.filter(status="pending").exists())

    def test_deleting_draft_product_removes_its_content_and_requests(self):
        self.client.force_login(self.manager)
        draft = Product.objects.create(product_type="course", title="d", slug="d", primary_domain=self.fpga)
        self.client.post(reverse("admin:content_section_add"), {"product": draft.pk, "title": "s", "order": 0})
        self.client.post(reverse("admin:products_product_delete", args=[draft.pk]), {"post": "yes"})
        self.assertFalse(Section.objects.filter(product_id=draft.pk).exists())
        self.assertFalse(ChangeRequest.objects.filter(object_id=draft.pk, content_type__model="product").exists())


class BundleTests(ContentTestCase):
    def product_post(self, product, **changes):
        data = {
            "product_type": product.product_type, "title": product.title, "slug": product.slug, "summary": "",
            "description": "", "intro_video_url": "", "primary_domain": product.primary_domain_id,
            "price": product.price, "sale_price": "", "related_products": [], "included_products": [],
        }
        data.update(changes)
        return self.client.post(reverse("admin:products_product_change", args=[product.pk]), data)

    def test_project_can_include_source_code_product(self):
        source = Product.objects.create(product_type="source", title="سورس", slug="src", primary_domain=self.fpga,
                                        price=500_000, is_published=True)
        self.client.force_login(self.admin)
        self.product_post(self.product, included_products=[source.pk])
        self.assertEqual(list(self.product.included_products.all()), [source])
        self.assertEqual(list(Product.objects.filter(included_products=source)), [self.product])

    def test_manager_cannot_bundle_other_domain_product(self):
        ai_product = Product.objects.create(product_type="source", title="AI src", slug="ai-src", primary_domain=self.ai)
        self.client.force_login(self.manager)
        response = self.product_post(self.product, included_products=[ai_product.pk])
        self.assertEqual(response.status_code, 200)  # form error

    def test_no_nested_bundles(self):
        source = Product.objects.create(product_type="source", title="s", slug="s", primary_domain=self.fpga)
        middle = Product.objects.create(product_type="project", title="m", slug="m", primary_domain=self.fpga)
        middle.included_products.add(source)
        self.client.force_login(self.admin)
        response = self.product_post(self.product, included_products=[middle.pk])
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.product.included_products.exists())

    def test_related_products_are_two_way(self):
        project = Product.objects.create(product_type="project", title="p", slug="p", primary_domain=self.fpga)
        self.client.force_login(self.admin)
        self.product_post(self.product, related_products=[project.pk])
        self.assertEqual(list(project.related_products.all()), [self.product])

    def test_product_is_not_offered_to_itself(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:products_product_change", args=[self.product.pk]))
        form = response.context["adminform"].form
        self.assertNotIn(self.product, form.fields["included_products"].queryset)
        self.assertNotIn(self.product, form.fields["related_products"].queryset)

    def test_outline_shows_sections(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:products_product_change", args=[self.product.pk]))
        self.assertContains(response, "فصل ۱")


def tearDownModule():
    shutil.rmtree(TEMP_PROTECTED, ignore_errors=True)
    shutil.rmtree(TEMP_MEDIA, ignore_errors=True)