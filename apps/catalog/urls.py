from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("rete/", views.lan_settings, name="lan_settings"),
]
