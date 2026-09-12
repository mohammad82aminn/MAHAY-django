from django.urls import path

from . import views

app_name = "commerce"

urlpatterns = [
    path("cart/", views.cart_view, name="cart"),
    path("cart/add/<slug:slug>/", views.add_to_cart, name="add_to_cart"),
    path("cart/remove/<slug:slug>/", views.remove_from_cart, name="remove_from_cart"),
    path("checkout/", views.checkout, name="checkout"),
    path("payment/callback/", views.payment_callback, name="payment_callback"),
    path("orders/", views.order_list, name="order_list"),
    path("orders/<str:number>/", views.order_detail, name="order_detail"),
    path("my/", views.library, name="library"),
]