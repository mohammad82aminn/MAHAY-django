from django.urls import path

from . import views

app_name = "approvals"

urlpatterns = [
    path("pending/<int:pk>/<str:field_name>/", views.pending_file, name="pending_file"),
]