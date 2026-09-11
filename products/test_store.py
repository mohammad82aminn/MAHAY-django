from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from accounts.roles import SITE_ADMINS_GROUP
from content.models import Lesson, Section
from domains.models import Domain

from .models import Product, ProductImage
from .templatetags.store import aparat_embed, fa_num, toman

COVER = "products/covers/test.png"


class StoreTestCase(TestCase):
    def setUp(self):
        self.fpga = Domain.objects.create(name="FPGA", slug="fpga")
        self.ai = Domain.objects.create(name="هوش مصنوعی", slug="ai")
        self.course = self.make("course", "دوره FPGA", "fpga-course", price=1_000_000, sale_price=800_000)
        self.project = self.make("project", "ربات FPGA", "fpga-robot", price=0)
        self.draft = self.make("course", "پیش‌نویس", "draft", is_published=False)

    def make(self, product_type, title, slug, domain=None, is_published=True, **kwargs):
        return Product.objects.create(
            product_type=product_type, title=title, slug=slug, primary_domain=domain or self.fpga,
            is_published=is_published, cover=COVER, **kwargs,
        )

    def listed(self, **params):
        response = self.client.get(reverse("products:list"), params)
        return list(response.context["products"])


class ListTests(StoreTestCase):
    def test_only_visible_products(self):
        self.make("course", "بایگانی", "archived", is_archived=True)
        self.assertCountEqual(self.listed(), [self.course, self.project])

    def test_filter_by_type_and_price(self):
        self.assertEqual(self.listed(type="project"), [self.project])
        self.assertEqual(self.listed(price="free"), [self.project])
        self.assertEqual(self.listed(price="paid"), [self.course])

    def test_domain_includes_related_products(self):
        ai_course = self.make("course", "AI", "ai-course", domain=self.ai)
        self.course.related_domains.add(self.ai)
        self.assertCountEqual(self.listed(domain="ai"), [ai_course, self.course])

    def test_inactive_domain_is_hidden(self):
        self.fpga.is_active = False
        self.fpga.save()
        self.assertEqual(self.listed(), [])

    def test_search(self):
        self.assertEqual(self.listed(q="ربات"), [self.project])

    def test_sort_by_price(self):
        self.assertEqual(self.listed(sort="cheap"), [self.project, self.course])


class DetailTests(StoreTestCase):
    def test_public_product_page(self):
        section = Section.objects.create(product=self.course, title="فصل یک", is_published=True)
        Lesson.objects.create(section=section, title="درس منتشرشده", is_published=True, duration_minutes=12)
        Lesson.objects.create(section=section, title="درس منتظر تأیید")
        ProductImage.objects.create(product=self.course, image="products/gallery/a.png", caption="عکس ۱", is_published=True)

        response = self.client.get(self.course.get_absolute_url())
        self.assertContains(response, "دوره FPGA")
        self.assertContains(response, "درس منتشرشده")
        self.assertNotContains(response, "درس منتظر تأیید")  # unpublished content is never shown
        self.assertContains(response, "عکس ۱")
        self.assertContains(response, "۸۰۰٬۰۰۰ تومان")

    def test_draft_is_hidden_from_public(self):
        self.assertEqual(self.client.get(self.draft.get_absolute_url()).status_code, 404)
        self.client.force_login(User.objects.create_user("09124444444", "S3cure-pass!"))
        self.assertEqual(self.client.get(self.draft.get_absolute_url()).status_code, 404)

    def test_managers_can_preview_draft(self):
        manager = User.objects.create_user("09121111111", "S3cure-pass!")
        manager.groups.add(self.fpga.group)
        self.client.force_login(manager)
        response = self.client.get(self.draft.get_absolute_url())
        self.assertContains(response, "پیش‌نمایش")

        admin = User.objects.create_user("09122222222", "S3cure-pass!")
        admin.groups.add(Group.objects.get(name=SITE_ADMINS_GROUP))
        self.client.force_login(admin)
        self.assertEqual(self.client.get(self.draft.get_absolute_url()).status_code, 200)

    def test_related_and_included_products(self):
        source = self.make("source", "سورس ربات", "robot-src", price=300_000)
        self.project.included_products.add(source)
        self.project.related_products.add(self.course)
        response = self.client.get(self.project.get_absolute_url())
        self.assertContains(response, "سورس ربات")
        self.assertContains(response, "دوره FPGA")

    def test_intro_video_is_embedded(self):
        self.course.intro_video_url = "https://www.aparat.com/v/abc123"
        self.course.save()
        response = self.client.get(self.course.get_absolute_url())
        self.assertContains(response, "aparat.com/video/video/embed/videohash/abc123/vt/frame")


class HomeTests(StoreTestCase):
    def test_home_shows_latest_products(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "دوره FPGA")
        self.assertContains(response, "ربات FPGA")
        self.assertNotContains(response, "پیش‌نویس")


class TemplateFilterTests(TestCase):
    def test_filters(self):
        self.assertEqual(fa_num(1500000), "۱٬۵۰۰٬۰۰۰")
        self.assertEqual(toman(0), "رایگان")
        self.assertEqual(toman(25000), "۲۵٬۰۰۰ تومان")
        self.assertEqual(aparat_embed("https://www.aparat.com/v/xyz9"),
                         "https://www.aparat.com/video/video/embed/videohash/xyz9/vt/frame")
        self.assertEqual(aparat_embed("https://example.com"), "")