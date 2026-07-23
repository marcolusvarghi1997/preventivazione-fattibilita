from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("rete/", views.lan_settings, name="lan_settings"),
    path("rete/accessi/<int:pk>/decisione/", views.decide_lan_access, name="decide_lan_access"),
    path("rete/accessi/<int:pk>/rimuovi/", views.delete_lan_access, name="delete_lan_access"),
]
