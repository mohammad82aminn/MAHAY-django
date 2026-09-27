"""
The approval workflow, exercised through the admin the way a person actually uses it.

Two things are being protected here. One is the site: a domain manager's edit must never change
what a visitor sees until a site admin has agreed to it. The other is the buyer: something
already sold is archived rather than deleted, so access survives.
"""
import shutil
import tempfile
from io import BytesIO

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import User
from accounts.roles import SITE_ADMINS_GROUP
from domains.models import Domain
from products.models import Product

from . import services
from .models import ChangeRequest

PASSWORD = "S3cure-pass!"
TEMP_MEDIA = tempfile.mkdtemp()


def image_file(name="cover.png"):
    buffer = BytesIO()
    Image.new("RGB", (10, 10), "blue").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ApprovalTestCase(TestCase):
    def setUp(self):
        self.fpga = Domain.objects.create(name="FPGA", slug="fpga")
        self.ai = Domain.objects.create(name="هوش مصنوعی", slug="ai")

        self.reviewer = User.objects.create_user("09120000000", PASSWORD, first_name="مدیرکل")
        self.reviewer.groups.add(Group.objects.get(name=SITE_ADMINS_GROUP))
        self.manager = self.domain_manager("09121111111", "علی", self.fpga)
        self.stranger = self.domain_manager("09122222222", "سارا", self.ai)

    @staticmethod
    def domain_manager(number, name, domain):
        user = User.objects.create_user(number, PASSWORD, first_name=name)
        user.groups.add(domain.managers_group)
        user.refresh_from_db()  # is_staff is set by a signal through a queryset update
        return user

    def make_product(self, domain=None, published=False, **extra):
        product = Product.objects.create(
            product_type=Product.Type.COURSE, title="مبانی FPGA", slug=extra.pop("slug", "fpga-basics"),
            primary_domain=domain or self.fpga, price=1_000_000, is_published=published,
            cover=image_file(), **extra,
        )
        return product

    def form_data(self, product, **changes):
        data = {
            "product_type": product.product_type, "title": product.title, "slug": product.slug,
            "summary": product.summary, "description": product.description,
            "primary_domain": product.primary_domain_id, "related_domains": [],
            "related_products": [], "price": product.price, "sale_price": "",
            "intro_video_url": "",
        }
        data.update(changes)
        return data

    def change_url(self, product):
        return reverse("admin:products_product_change", args=[product.pk])

    def pending(self, product, action):
        return services.pending_request(product, action)


class WhoMaySeeAndDecideTests(ApprovalTestCase):
    def test_a_manager_only_sees_their_own_domain(self):
        mine = self.make_product(self.fpga)
        theirs = self.make_product(self.ai, slug="ai-course")

        self.client.force_login(self.manager)
        listed = self.client.get(reverse("admin:products_product_changelist")).context["cl"].queryset
        self.assertIn(mine, listed)
        self.assertNotIn(theirs, listed)

    def test_a_manager_cannot_publish_by_hand(self):
        product = self.make_product()
        self.client.force_login(self.manager)
        response = self.client.get(self.change_url(product))
        readonly = response.context["adminform"].model_admin.get_readonly_fields(response.wsgi_request, product)

        self.assertIn("is_published", readonly)
        self.assertIn("is_archived", readonly)

    def test_who_decides_what(self):
        """A site admin decides anything open; a domain manager only what waits on their own desk."""
        from django.contrib import admin

        model_admin = admin.site._registry[ChangeRequest]
        expert = User.objects.create_user("09123333333", PASSWORD)
        expert.groups.add(self.fpga.experts_group)
        on_desk = services.submit(self.make_product(), ChangeRequest.Action.CREATE, expert, self.fpga)
        at_admins = services.submit(self.make_product(slug="mine"), ChangeRequest.Action.CREATE, self.manager, self.fpga)
        self.assertEqual((on_desk.stage, at_admins.stage), (ChangeRequest.Stage.DOMAIN, ChangeRequest.Stage.ADMIN))

        fake = type("Request", (), {})()
        for user, request, allowed in (
            (self.reviewer, on_desk, True), (self.reviewer, at_admins, True),
            (self.manager, on_desk, True), (self.manager, at_admins, False),
            (self.stranger, on_desk, False), (expert, on_desk, False),
        ):
            with self.subTest(user=user.mobile_number, stage=request.stage):
                fake.user = user
                self.assertIs(model_admin.has_change_permission(fake, request), allowed)

    def test_a_manager_sees_only_their_domain_s_requests(self):
        mine = self.make_product(self.fpga)
        theirs = self.make_product(self.ai, slug="ai-course")
        services.submit(mine, ChangeRequest.Action.CREATE, self.manager, self.fpga)
        services.submit(theirs, ChangeRequest.Action.CREATE, self.stranger, self.ai)

        self.client.force_login(self.manager)
        listed = self.client.get(reverse("admin:approvals_changerequest_changelist")).context["cl"].queryset
        self.assertEqual([r.object_repr for r in listed], [str(mine)])


class SubmittingTests(ApprovalTestCase):
    def test_a_new_item_is_saved_hidden_and_asks_to_be_published(self):
        self.client.force_login(self.manager)
        self.client.post(reverse("admin:products_product_add"), {
            "product_type": "course", "title": "دوره تازه", "slug": "new-course",
            "summary": "", "description": "", "primary_domain": self.fpga.pk,
            "related_domains": [], "related_products": [], "price": 500_000, "sale_price": "",
            "intro_video_url": "",
        })
        product = Product.objects.get(slug="new-course")

        self.assertFalse(product.is_published)
        self.assertIsNotNone(self.pending(product, ChangeRequest.Action.CREATE))

    def test_editing_a_published_item_leaves_the_site_untouched(self):
        product = self.make_product(published=True)
        self.client.force_login(self.manager)
        self.client.post(self.change_url(product), self.form_data(product, title="عنوان تازه"))

        product.refresh_from_db()
        self.assertEqual(product.title, "مبانی FPGA")  # a visitor still sees this
        request = self.pending(product, ChangeRequest.Action.UPDATE)
        self.assertEqual(request.data, {"title": "عنوان تازه"})

    def test_undoing_the_edits_takes_the_request_back(self):
        product = self.make_product(published=True)
        self.client.force_login(self.manager)
        self.client.post(self.change_url(product), self.form_data(product, title="عنوان تازه"))
        self.client.post(self.change_url(product), self.form_data(product))  # back to how it was

        self.assertIsNone(self.pending(product, ChangeRequest.Action.UPDATE))

    def test_a_site_admin_changes_things_straight_away(self):
        product = self.make_product(published=True)
        self.client.force_login(self.reviewer)
        self.client.post(self.change_url(product), self.form_data(product, title="عنوان تازه"))

        product.refresh_from_db()
        self.assertEqual(product.title, "عنوان تازه")
        self.assertIsNone(self.pending(product, ChangeRequest.Action.UPDATE))


class DecidingTests(ApprovalTestCase):
    def test_approving_publishes_the_item(self):
        product = self.make_product()
        request = services.submit(product, ChangeRequest.Action.CREATE, self.manager, self.fpga)
        services.approve(request, self.reviewer)

        product.refresh_from_db()
        request.refresh_from_db()
        self.assertTrue(product.is_published)
        self.assertEqual(request.status, ChangeRequest.Status.APPROVED)
        self.assertEqual(request.reviewed_by, self.reviewer)

    def test_approving_an_edit_writes_it_to_the_live_item(self):
        product = self.make_product(published=True)
        request = services.submit(product, ChangeRequest.Action.UPDATE, self.manager, self.fpga,
                                  {"title": "عنوان تازه", "price": 2_000_000})
        services.approve(request, self.reviewer)

        product.refresh_from_db()
        self.assertEqual(product.title, "عنوان تازه")
        self.assertEqual(product.price, 2_000_000)

    def test_rejecting_leaves_the_live_item_as_it_was(self):
        product = self.make_product(published=True)
        request = services.submit(product, ChangeRequest.Action.UPDATE, self.manager, self.fpga,
                                  {"title": "عنوان تازه"})
        services.reject(request, self.reviewer, "مناسب نیست")

        product.refresh_from_db()
        request.refresh_from_db()
        self.assertEqual(product.title, "مبانی FPGA")
        self.assertEqual(request.status, ChangeRequest.Status.REJECTED)
        self.assertEqual(request.review_note, "مناسب نیست")


class RemovingTests(ApprovalTestCase):
    def test_a_published_item_is_never_deleted_by_a_manager(self):
        # Somebody may already have bought it, and buying is meant to last
        product = self.make_product(published=True)
        self.client.force_login(self.manager)
        self.client.post(reverse("admin:products_product_delete", args=[product.pk]), {"post": "yes"})

        self.assertTrue(Product.objects.filter(pk=product.pk).exists())
        self.assertIsNotNone(self.pending(product, ChangeRequest.Action.ARCHIVE))

    def test_approving_the_removal_takes_it_off_the_store_but_keeps_it(self):
        product = self.make_product(published=True)
        request = services.submit(product, ChangeRequest.Action.ARCHIVE, self.manager, self.fpga)
        services.approve(request, self.reviewer)

        product.refresh_from_db()
        self.assertTrue(product.is_archived)
        self.assertNotIn(product, Product.objects.visible())

    def test_a_draft_nobody_has_seen_is_simply_deleted(self):
        product = self.make_product(published=False)
        self.client.force_login(self.manager)
        self.client.post(reverse("admin:products_product_delete", args=[product.pk]), {"post": "yes"})

        self.assertFalse(Product.objects.filter(pk=product.pk).exists())

    def test_bulk_delete_is_not_offered(self):
        # It would go around every rule above, so it is removed for everyone
        from django.contrib import admin

        model_admin = admin.site._registry[Product]
        for user in (self.manager, self.reviewer):
            with self.subTest(user=user.first_name):
                fake = type("Request", (), {"user": user, "GET": {}})()
                self.assertNotIn("delete_selected", model_admin.get_actions(fake))


def tearDownModule():
    shutil.rmtree(TEMP_MEDIA, ignore_errors=True)
