"""
The two desks new content passes: the domain's managers, then the site admins.

Exercised through the admin panel the way people use it, because that is where the rules live:
an expert touches only their own unpublished work, a manager corrects it and sends it on (or
back), and a site admin publishes. Turning something down tells the people it concerns at once.
"""
import shutil
import tempfile

from django.test import override_settings
from django.urls import reverse

from accounts.models import User
from content.models import Lesson, Section
from inbox.models import Delivery, Message
from products.models import Product

from . import services
from .models import ChangeRequest, ReviewEvent
from .tests import PASSWORD, ApprovalTestCase, image_file

TEMP_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class TwoDeskTestCase(ApprovalTestCase):
    def setUp(self):
        super().setUp()  # self.manager manages FPGA, self.stranger manages AI, self.reviewer is a site admin
        self.expert = self.person("09123333333", "رضا", self.fpga.experts_group)
        self.colleague = self.person("09124444444", "مریم", self.fpga.experts_group)

    @staticmethod
    def person(number, name, group):
        user = User.objects.create_user(number, PASSWORD, first_name=name)
        user.groups.add(group)
        user.refresh_from_db()
        return user

    def add_product(self, user, slug="new-course", domain=None, **changes):
        self.client.force_login(user)
        data = {
            "product_type": "course", "title": "دوره تازه", "slug": slug, "summary": "", "description": "",
            "primary_domain": (domain or self.fpga).pk, "related_domains": [], "related_products": [],
            "price": 500_000, "sale_price": "", "intro_video_url": "",
            "cover": image_file(),
        }
        data.update(changes)
        self.client.post(reverse("admin:products_product_add"), data)
        return Product.objects.get(slug=slug)

    def decide(self, user, request, status, note=""):
        self.client.force_login(user)
        return self.client.post(reverse("admin:approvals_changerequest_change", args=[request.pk]),
                                {"status": status, "review_note": note})

    def inbox_of(self, user):
        return Message.objects.filter(deliveries__user=user)


class WhichDeskTests(TwoDeskTestCase):
    def test_an_expert_s_work_goes_to_the_domain_managers_first(self):
        product = self.add_product(self.expert)
        request = self.pending(product, ChangeRequest.Action.CREATE)
        self.assertEqual(request.stage, ChangeRequest.Stage.DOMAIN)
        self.assertEqual(product.created_by, self.expert)
        self.assertEqual(list(product.review_events.values_list("kind", flat=True)), [ReviewEvent.Kind.SUBMITTED])

    def test_a_manager_s_own_work_goes_straight_to_the_site_admins(self):
        product = self.add_product(self.manager)
        self.assertEqual(self.pending(product, ChangeRequest.Action.CREATE).stage, ChangeRequest.Stage.ADMIN)

    def test_a_domain_without_a_manager_sends_everything_to_the_site_admins(self):
        self.manager.groups.remove(self.fpga.managers_group)
        product = self.add_product(self.expert)
        self.assertEqual(self.pending(product, ChangeRequest.Action.CREATE).stage, ChangeRequest.Stage.ADMIN)

    def test_a_domain_may_have_two_managers_and_either_may_send_it_on(self):
        second = self.person("09125555555", "نرگس", self.fpga.managers_group)
        request = self.pending(self.add_product(self.expert), ChangeRequest.Action.CREATE)
        self.decide(second, request, "approved")
        request.refresh_from_db()
        self.assertEqual(request.stage, ChangeRequest.Stage.ADMIN)


class ManagersDeskTests(TwoDeskTestCase):
    def test_sending_it_on_takes_its_new_lessons_along(self):
        product = self.add_product(self.expert)
        section = Section.objects.create(product=product, title="فصل", created_by=self.expert)
        section_request = services.submit(section, ChangeRequest.Action.CREATE, self.expert, self.fpga)
        request = self.pending(product, ChangeRequest.Action.CREATE)

        self.decide(self.manager, request, "approved", "خوب است")
        for item in (request, section_request):
            item.refresh_from_db()
            self.assertEqual((item.status, item.stage), (ChangeRequest.Status.PENDING, ChangeRequest.Stage.ADMIN))
        product.refresh_from_db()
        self.assertFalse(product.is_published)  # only a site admin publishes
        forwarded = product.review_events.get(kind=ReviewEvent.Kind.FORWARDED)
        self.assertEqual((forwarded.actor, forwarded.note), (self.manager, "خوب است"))

    def test_turning_it_down_sends_it_back_to_the_expert_with_the_reason(self):
        request = self.pending(self.add_product(self.expert), ChangeRequest.Action.CREATE)
        self.decide(self.manager, request, "rejected", "ویدیوی معرفی ندارد")
        request.refresh_from_db()
        self.assertEqual(request.status, ChangeRequest.Status.REJECTED)
        [message] = self.inbox_of(self.expert)
        self.assertTrue(message.from_system)
        self.assertIn("ویدیوی معرفی ندارد", message.body)
        self.assertFalse(self.inbox_of(self.manager).exists())  # they did it; no need to tell them

    def test_a_manager_corrects_the_draft_and_the_expert_sees_what_changed(self):
        product = self.add_product(self.expert, title="دوره‌ی تازه با غلط")
        self.client.force_login(self.manager)
        self.client.post(self.change_url(product), self.form_data(product, title="دوره‌ی تازه"))

        request = self.pending(product, ChangeRequest.Action.CREATE)
        self.assertEqual((request.stage, request.submitted_by), (ChangeRequest.Stage.DOMAIN, self.expert))
        edit = product.review_events.get(kind=ReviewEvent.Kind.EDITED)
        self.assertEqual(edit.actor, self.manager)
        self.assertIn({"field": "عنوان", "old": "دوره‌ی تازه با غلط", "new": "دوره‌ی تازه"}, edit.changes)

        self.client.force_login(self.expert)
        self.assertContains(self.client.get(self.change_url(product)), "دوره‌ی تازه با غلط")

    def test_a_manager_cannot_decide_what_already_reached_the_site_admins_or_another_domain(self):
        at_admins = self.pending(self.add_product(self.manager), ChangeRequest.Action.CREATE)
        ai_expert = self.person("09126666666", "امید", self.ai.experts_group)
        other = self.pending(self.add_product(ai_expert, slug="ai-course", domain=self.ai), ChangeRequest.Action.CREATE)
        for request in (at_admins, other):
            self.decide(self.manager, request, "approved")
            request.refresh_from_db()
            self.assertEqual(request.status, ChangeRequest.Status.PENDING)
        self.assertEqual(other.stage, ChangeRequest.Stage.DOMAIN)

    def test_the_red_number_counts_only_the_visitor_s_own_desk(self):
        from django.contrib import admin

        model_admin = admin.site._registry[ChangeRequest]
        self.add_product(self.expert)                   # on the FPGA managers' desk
        self.add_product(self.manager, slug="managers")  # on the site admins' desk
        fake = type("Request", (), {})()
        for user, expected in ((self.manager, 1), (self.reviewer, 1), (self.stranger, 0)):
            fake.user = user
            self.assertEqual(model_admin.pending_count(fake), expected, user.first_name)


class SiteAdminsDeskTests(TwoDeskTestCase):
    def test_turning_down_tells_the_expert_and_the_domain_managers(self):
        second = self.person("09125555555", "نرگس", self.fpga.managers_group)
        request = self.pending(self.add_product(self.expert), ChangeRequest.Action.CREATE)
        self.decide(self.manager, request, "approved")
        self.decide(self.reviewer, request, "rejected", "قیمت مناسب نیست")

        for user in (self.expert, self.manager, second):
            [message] = self.inbox_of(user)
            self.assertIn("قیمت مناسب نیست", message.body)
        self.assertFalse(self.inbox_of(self.reviewer).exists())

    def test_approving_publishes_and_it_shows_in_the_history(self):
        product = self.add_product(self.expert)
        request = self.pending(product, ChangeRequest.Action.CREATE)
        self.decide(self.manager, request, "approved")
        self.decide(self.reviewer, request, "approved")
        product.refresh_from_db()
        self.assertTrue(product.is_published)
        self.assertEqual(
            list(product.review_events.values_list("kind", flat=True)),
            [ReviewEvent.Kind.SUBMITTED, ReviewEvent.Kind.FORWARDED, ReviewEvent.Kind.APPROVED],
        )


class WhatAnExpertMayTouchTests(TwoDeskTestCase):
    def test_their_own_draft_yes_a_colleague_s_or_anything_published_no(self):
        mine = self.add_product(self.expert, slug="mine")
        theirs = self.add_product(self.colleague, slug="theirs")
        published = self.make_product(published=True, slug="live")
        self.client.force_login(self.expert)

        self.client.post(self.change_url(mine), self.form_data(mine, title="عنوان من"))
        mine.refresh_from_db()
        self.assertEqual(mine.title, "عنوان من")

        for product in (theirs, published):
            with self.subTest(product=product.slug):
                response = self.client.post(self.change_url(product), self.form_data(product, title="دست‌کاری"))
                self.assertEqual(response.status_code, 403)
                product.refresh_from_db()
                self.assertNotEqual(product.title, "دست‌کاری")
                self.assertEqual(self.client.get(self.change_url(product)).status_code, 200)  # still readable
        self.assertIsNone(self.pending(published, ChangeRequest.Action.UPDATE))

    def test_only_a_manager_asks_to_remove_something_published(self):
        published = self.make_product(published=True, slug="live")
        delete_url = reverse("admin:products_product_delete", args=[published.pk])
        self.client.force_login(self.expert)
        self.assertEqual(self.client.post(delete_url, {"post": "yes"}).status_code, 403)
        self.assertIsNone(self.pending(published, ChangeRequest.Action.ARCHIVE))

        self.client.force_login(self.manager)
        self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(self.pending(published, ChangeRequest.Action.ARCHIVE).stage, ChangeRequest.Stage.ADMIN)

    def test_their_own_draft_may_be_deleted(self):
        mine = self.add_product(self.expert, slug="mine")
        self.client.force_login(self.expert)
        self.client.post(reverse("admin:products_product_delete", args=[mine.pk]), {"post": "yes"})
        self.assertFalse(Product.objects.filter(pk=mine.pk).exists())

    def test_changing_it_after_the_manager_sent_it_on_brings_it_back_to_the_manager(self):
        mine = self.add_product(self.expert, slug="mine")
        request = self.pending(mine, ChangeRequest.Action.CREATE)
        self.decide(self.manager, request, "approved")
        self.client.force_login(self.expert)
        self.client.post(self.change_url(mine), self.form_data(mine, title="نسخه‌ی تازه"))
        request.refresh_from_db()
        self.assertEqual(request.stage, ChangeRequest.Stage.DOMAIN)

    def test_old_content_with_no_recorded_author_is_left_to_the_managers(self):
        section = Section.objects.create(product=self.make_product(slug="old"), title="فصل قدیمی")
        lesson = Lesson.objects.create(section=section, title="درس قدیمی")
        self.client.force_login(self.expert)
        response = self.client.post(reverse("admin:content_lesson_change", args=[lesson.pk]), {
            "section": section.pk, "title": "تغییر", "order": 0, "body": "", "video_url": "", "duration_minutes": "",
        })
        self.assertEqual(response.status_code, 403)


class SystemMessageTests(TwoDeskTestCase):
    def test_the_inbox_says_it_came_from_the_site(self):
        request = self.pending(self.add_product(self.expert), ChangeRequest.Action.CREATE)
        self.decide(self.manager, request, "rejected", "ناقص است")
        delivery = Delivery.objects.get(user=self.expert)
        self.client.force_login(self.expert)
        self.assertContains(self.client.get(reverse("admin:inbox_message_changelist")), "سامانه")
        self.assertContains(self.client.get(reverse("admin:inbox_message_detail", args=[delivery.message.pk])), "سامانه")


def tearDownModule():
    shutil.rmtree(TEMP_MEDIA, ignore_errors=True)
