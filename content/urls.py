from django.urls import path

from . import views

app_name = "content"

urlpatterns = [
    path("files/<str:kind>/<int:pk>/", views.protected_file, name="protected_file"),
]