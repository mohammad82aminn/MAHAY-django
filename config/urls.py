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

from products.views import HomeView

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("products/", include("products.urls")),
    path("accounts/", include("accounts.urls")),
    path("shop/", include("commerce.urls")),
    path("services/", include("services.urls")),
    path("content/", include("content.urls")),
    path("approvals/", include("approvals.urls")),
    path("admin/", admin.site.urls),
    path("p/", include("pages.urls")),  # last: /p/<slug>/ must not shadow the other sections
]

if settings.DEBUG:
    # Development only: let Django serve uploaded files
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)