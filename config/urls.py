"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.decorators.cache import cache_control

from products.views import HomeView

# The panel's own name, instead of Django's «مدیریت Django»
admin.site.site_header = "پنل مدیریت MAHAY"
admin.site.site_title = "پنل MAHAY"
admin.site.index_title = "پیشخوان"

# The translation catalog every list and form page loads before it can draw. Django rebuilds it
# on each request and sends it uncached (≈200ms, render-blocking, on every click in the panel).
# It is the same text for everyone, so the browser may keep it a day; admin_view still requires
# a logged-in staff member, and «private» keeps it out of shared caches.
admin.site.i18n_javascript = cache_control(private=True, max_age=60 * 60 * 24)(admin.site.i18n_javascript)

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("products/", include("products.urls")),
    path("accounts/", include("accounts.urls")),
    path("shop/", include("commerce.urls")),
    path("services/", include("services.urls")),
    path("collaboration/", include("collaboration.urls")),
    path("content/", include("content.urls")),
    path("approvals/", include("approvals.urls")),
    path("admin/", admin.site.urls),
    path("p/", include("pages.urls")),  # last: /p/<slug>/ must not shadow the other sections
]

# What a visitor sees on an error while DEBUG is off: our own page, no details (see config/errors.py)
handler400 = "config.errors.bad_request"
handler403 = "config.errors.permission_denied"
handler404 = "config.errors.page_not_found"
handler500 = "config.errors.server_error"

if settings.DEBUG:
    # Development only: let Django serve uploaded files
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)