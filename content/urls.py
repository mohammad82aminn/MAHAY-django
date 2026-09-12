from django.urls import path

from . import views

app_name = "content"

urlpatterns = [
    path("files/<str:kind>/<int:pk>/", views.protected_file, name="protected_file"),
    path("learn/<slug:slug>/", views.learn, name="learn"),
    path("learn/<slug:slug>/lesson/<int:pk>/", views.lesson_view, name="lesson"),
    path("progress/<int:pk>/", views.save_progress, name="save_progress"),
]