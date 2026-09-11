import shutil
import tempfile
from io import BytesIO

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import User
from accounts.roles import SITE_ADMINS_GROUP
from approvals.models import ChangeRequest
from domains.models import Domain

from .models import Product

PASSWORD = "S3cure-pass!"
TEMP_MEDIA = tempfile.mkdtemp()


def product_data(**overrides):
    """POST data for the product admin form."""
    data = {
        "product_type": "course", "title": "مبانی FPGA", "slug": "fpga-basics", "summary": "", "description": "",
        "primary_domain": "", "related_domains": [], "price": 1_000_000, "sale_price": "",
    }
    data.update(overrides)
    return data


def image_file(name="cover.png"):
    buffer = BytesIO()
    Image.new("RGB", (10, 10), "blue").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class ProductModelTests(TestCase):
    def setUp(self):
        self.domain = Domain.objects.create(name="FPGA", slug="fpga")

    def make(self, **kwargs):
        return Product(product_type="course", title="t", slug="t", primary_domain=self.domain, **kwargs)

    def test_sale_price_must_be_lower(self):
        with self.assertRaises(ValidationError):
            self.make(price=100, sale_price=100).full_clean()

    def test_free_product_has_no_sale_price(self):
        with self.assertRaises(ValidationError):
            self.make(price=0, sale_price=0).full_clean()

    def test_prices(self):
        product = self.make(price=200_000, sale_price=150_000)
        self.assertEqual(product.final_price, 150_000)
        self.assertEqual(product.discount_percent, 25)
        self.assertTrue(self.make(price=0).is_free)

    def test_visible_only_published_and_not_archived(self):
        Product.objects.create(product_type="course", title="a", slug="a", primary_domain=self.domain)
        shown = Product.objects.create(product_type="course", title="b", slug="b", primary_domain=self.domain,
                                       is_published=True)
        Product.objects.create(product_type="course", title="c", slug="c", primary_domain=self.domain,
                               is_published=True, is_archived=True)
        self.assertEqual(list(Product.objects.visible()), [shown])


class ApprovalFlowTestCase(TestCase):
    def setUp(self):
        self.fpga = Domain.objects.create(name="FPGA", slug="fpga")
        self.ai = Domain.objects.create(name="هوش مصنوعی", slug="ai")

        self.manager = User.objects.create_user("09121111111", PASSWORD)
        self.manager.groups.add(self.fpga.group)
        self.admin = User.objects.create_user("09122222222", PASSWORD)
        self.admin.groups.add(Group.objects.get(name=SITE_ADMINS_GROUP))

        self.add_url = reverse("admin:products_product_add")

    def change_url(self, product):
        return reverse("admin:products_product_change", args=[product.pk])

    def published(self, **kwargs):
        values = {"product_type": "course", "title": "مبانی FPGA", "slug": "fpga-basics",
                  "primary_domain": self.fpga, "price": 1_000_000, "is_published": True}
        values.update(kwargs)
        return Product.objects.create(**values)

    def approve_as_admin(self, change_request):
        self.client.force_login(self.admin)
        url = reverse("admin:approvals_changerequest_change", args=[change_request.pk])
        return self.client.post(url, {"status": "approved", "review_note": ""})


class ManagerCreatesProductTests(ApprovalFlowTestCase):
    def test_new_product_waits_for_approval(self):
        self.client.force_login(self.manager)
        response = self.client.post(self.add_url, product_data(primary_domain=self.fpga.pk))
        self.assertEqual(response.status_code, 302)

        product = Product.objects.get()
        self.assertFalse(product.is_published)
        self.assertEqual(product.created_by, self.manager)
        self.assertFalse(Product.objects.visible().exists())
        request = ChangeRequest.objects.get(action="create", status="pending")
        self.assertEqual(request.domain, self.fpga)

        self.approve_as_admin(request)
        product.refresh_from_db()
        self.assertTrue(product.is_published)

    def test_manager_cannot_use_other_domain(self):
        self.client.force_login(self.manager)
        response = self.client.post(self.add_url, product_data(primary_domain=self.ai.pk))
        self.assertEqual(response.status_code, 200)  # form error
        self.assertFalse(Product.objects.exists())

    def test_manager_sees_only_own_domain_products(self):
        own = self.published()
        self.published(title="AI", slug="ai-course", primary_domain=self.ai)
        related_only = self.published(title="AI+FPGA", slug="ai-fpga", primary_domain=self.ai)
        related_only.related_domains.add(self.fpga)

        self.client.force_login(self.manager)
        response = self.client.get(reverse("admin:products_product_changelist"))
        self.assertEqual(list(response.context["cl"].queryset), [own])

    def test_manager_cannot_publish_directly(self):
        self.client.force_login(self.manager)
        self.client.post(self.add_url, product_data(primary_domain=self.fpga.pk, is_published="on"))
        self.assertFalse(Product.objects.get().is_published)


class ManagerEditsPublishedProductTests(ApprovalFlowTestCase):
    def setUp(self):
        super().setUp()
        self.product = self.published()
        self.client.force_login(self.manager)

    def edit(self, **changes):
        return self.client.post(self.change_url(self.product), product_data(primary_domain=self.fpga.pk, **changes))

    def test_live_version_stays_until_approval(self):
        self.edit(title="عنوان جدید", price=900_000, related_domains=[self.ai.pk])

        self.product.refresh_from_db()
        self.assertEqual(self.product.title, "مبانی FPGA")
        self.assertFalse(self.product.related_domains.exists())
        request = ChangeRequest.objects.get(action="update", status="pending")
        self.assertEqual(request.data, {"title": "عنوان جدید", "price": 900_000, "related_domains": [self.ai.pk]})

        self.approve_as_admin(request)
        self.product.refresh_from_db()
        self.assertEqual(self.product.title, "عنوان جدید")
        self.assertEqual(self.product.price, 900_000)
        self.assertEqual(list(self.product.related_domains.all()), [self.ai])

    def test_form_shows_pending_version_and_new_edit_replaces_it(self):
        self.edit(title="نسخه ۱")
        response = self.client.get(self.change_url(self.product))
        self.assertEqual(response.context["adminform"].form.initial["title"], "نسخه ۱")

        self.edit(title="نسخه ۲")
        request = ChangeRequest.objects.get(action="update", status="pending")
        self.assertEqual(request.data, {"title": "نسخه ۲"})

    def test_undoing_all_edits_withdraws_request(self):
        self.edit(title="نسخه ۱")
        self.edit()  # back to the live values
        self.assertFalse(ChangeRequest.objects.filter(action="update", status="pending").exists())

    def test_rejected_edit_is_discarded(self):
        self.edit(title="عنوان بد")
        request = ChangeRequest.objects.get(action="update")
        self.client.force_login(self.admin)
        self.client.post(reverse("admin:approvals_changerequest_change", args=[request.pk]),
                         {"status": "rejected", "review_note": "عنوان مناسب نیست"})
        request.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(request.status, "rejected")
        self.assertEqual(request.review_note, "عنوان مناسب نیست")
        self.assertEqual(self.product.title, "مبانی FPGA")

    @override_settings(MEDIA_ROOT=TEMP_MEDIA)
    def test_new_cover_waits_for_approval(self):
        self.edit(cover=image_file())
        self.product.refresh_from_db()
        self.assertFalse(self.product.cover)

        request = ChangeRequest.objects.get(action="update")
        self.assertTrue(request.data["cover"].startswith("pending/"))
        self.approve_as_admin(request)
        self.product.refresh_from_db()
        self.assertEqual(self.product.cover.name, request.data["cover"])

    def test_delete_request_archives_after_approval(self):
        self.client.post(reverse("admin:products_product_delete", args=[self.product.pk]), {"post": "yes"})
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_archived)

        self.approve_as_admin(ChangeRequest.objects.get(action="archive"))
        self.product.refresh_from_db()
        self.assertTrue(self.product.is_archived)
        self.assertFalse(Product.objects.visible().exists())

    def test_manager_cannot_decide_requests(self):
        self.edit(title="x")
        request = ChangeRequest.objects.get(action="update")
        url = reverse("admin:approvals_changerequest_change", args=[request.pk])
        self.assertEqual(self.client.get(url).status_code, 200)  # can view (e.g. to read the rejection note)
        self.client.post(url, {"status": "approved"})
        request.refresh_from_db()
        self.assertEqual(request.status, "pending")


class DraftAndAdminTests(ApprovalFlowTestCase):
    def test_manager_edits_draft_directly_and_can_delete_it(self):
        self.client.force_login(self.manager)
        self.client.post(self.add_url, product_data(primary_domain=self.fpga.pk))
        product = Product.objects.get()
        self.client.post(self.change_url(product), product_data(primary_domain=self.fpga.pk, title="اصلاح‌شده"))
        product.refresh_from_db()
        self.assertEqual(product.title, "اصلاح‌شده")  # nobody sees drafts, so no waiting needed
        self.assertEqual(ChangeRequest.objects.filter(action="create", status="pending").count(), 1)

        self.client.post(reverse("admin:products_product_delete", args=[product.pk]), {"post": "yes"})
        self.assertFalse(Product.objects.exists())
        self.assertFalse(ChangeRequest.objects.exists())  # its requests are removed too

    def test_site_admin_changes_apply_immediately(self):
        product = self.published()
        self.client.force_login(self.admin)
        self.client.post(self.change_url(product), product_data(primary_domain=self.fpga.pk, title="مستقیم",
                                                                is_published="on"))
        product.refresh_from_db()
        self.assertEqual(product.title, "مستقیم")
        self.assertFalse(ChangeRequest.objects.exists())

    def test_site_admin_publishing_directly_closes_request(self):
        self.client.force_login(self.manager)
        self.client.post(self.add_url, product_data(primary_domain=self.fpga.pk))
        product = Product.objects.get()

        self.client.force_login(self.admin)
        self.client.post(self.change_url(product), product_data(primary_domain=self.fpga.pk, is_published="on"))
        request = ChangeRequest.objects.get(action="create")
        self.assertEqual(request.status, "approved")
        self.assertEqual(request.reviewed_by, self.admin)

    def test_site_admin_delete_archives_published_product(self):
        product = self.published()
        self.client.force_login(self.admin)
        self.client.post(reverse("admin:products_product_delete", args=[product.pk]), {"post": "yes"})
        product.refresh_from_db()
        self.assertTrue(product.is_archived)

    def test_outdated_request_is_not_applied(self):
        product = self.published()
        self.published(title="other", slug="taken")
        self.client.force_login(self.manager)
        self.client.post(self.change_url(product), product_data(primary_domain=self.fpga.pk, slug="free-slug"))
        request = ChangeRequest.objects.get(action="update")
        request.data = {"slug": "taken"}  # meanwhile the slug was taken by another product
        request.save()

        self.approve_as_admin(request)
        request.refresh_from_db()
        self.assertEqual(request.status, "pending")
        product.refresh_from_db()
        self.assertEqual(product.slug, "fpga-basics")


def tearDownModule():
    shutil.rmtree(TEMP_MEDIA, ignore_errors=True)