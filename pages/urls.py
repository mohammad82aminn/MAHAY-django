from django.urls import path

from . import views

app_name = "pages"

urlpatterns = [
    path("contact/", views.ContactView.as_view(), name="contact"),
    path("<slug:slug>/", views.PageDetailView.as_view(), name="detail"),
]