from django.urls import path

from . import views

app_name = "services"

urlpatterns = [
    path("project/", views.project_request, name="project"),
    path("consulting/", views.consulting_request, name="consulting"),
    path("submitted/<str:code>/", views.submitted, name="submitted"),
    path("my/", views.my_requests, name="my_requests"),
    path("files/<str:kind>/<int:pk>/", views.attachment, name="attachment"),
]