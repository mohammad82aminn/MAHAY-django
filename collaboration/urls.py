from django.urls import path

from . import views

app_name = "collaboration"

urlpatterns = [
    path("apply/", views.apply, name="apply"),
    path("file/<int:pk>/", views.download, name="file"),
]
