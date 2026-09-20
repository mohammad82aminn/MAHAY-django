"""
The کارپوشه is registered only to earn a place in the admin menu and a set of urls under it.

Every default admin page is replaced: get_urls() does not call super(), so there is no changelist,
no change form and no delete view to fall back on — the only way in is through inbox.views, and
each of those starts from services.visible_messages(). That matters here because the full-access
groups hold every permission of the site, and a permission must not be what decides whether one
colleague can read another's messages.
"""
from django.contrib import admin
from django.urls import path

from . import services, views
from .models import Message


@admin.register(Message)
class InboxAdmin(admin.ModelAdmin):
    def get_urls(self):
        page = self.admin_site.admin_view
        return [
            path("", page(views.inbox), name="inbox_message_changelist"),
            path("sent/", page(views.sent_box), name="inbox_message_sent"),
            path("compose/", page(views.compose), name="inbox_message_compose"),
            path("<int:pk>/", page(views.message_detail), name="inbox_message_detail"),
            path("<int:pk>/reply/", page(views.compose), name="inbox_message_reply"),
            path("<int:pk>/archive/", page(views.archive), name="inbox_message_archive"),
            path("file/<int:pk>/", page(views.download), name="inbox_message_file"),
        ]

    def get_queryset(self, request):
        return services.visible_messages(request.user)

    def has_module_permission(self, request):
        return services.has_inbox(request.user)

    def has_view_permission(self, request, obj=None):
        return services.has_inbox(request.user)

    def has_add_permission(self, request):
        return False  # composing happens on our own page

    def has_change_permission(self, request, obj=None):
        return False  # a sent message is a record

    def has_delete_permission(self, request, obj=None):
        return False  # archiving hides a message; nothing is ever removed
