from django.urls import path
from apps.reports.views import quote_pdf
from . import views

app_name = "quotes"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("preventivi/cerca/", views.quote_search, name="search"),
    path("preventivi/nuovo/", views.quote_general, name="create"),
    path("preventivi/<int:pk>/dati/", views.quote_general, name="general"),
    path("preventivi/<int:pk>/articoli/", views.quote_items, name="items"),
    path("preventivi/<int:pk>/articoli/aggiungi/", views.item_add, name="item_add"),
    path("preventivi/<int:pk>/articoli/<int:item_id>/modifica/", views.item_edit, name="item_edit"),
    path("preventivi/<int:pk>/articoli/<int:item_id>/duplica/", views.item_duplicate, name="item_duplicate"),
    path("preventivi/<int:pk>/articoli/<int:item_id>/rimuovi/", views.item_delete, name="item_delete"),
    path("preventivi/<int:pk>/articoli/<int:item_id>/materiali/aggiungi/", views.material_add, name="material_add"),
    path("preventivi/<int:pk>/materiali/<int:material_id>/rimuovi/", views.material_delete, name="material_delete"),
    path("preventivi/<int:pk>/lavorazioni/", views.quote_work, name="work"),
    path("preventivi/<int:pk>/fasi/<int:phase_id>/salva/", views.phase_update, name="phase_update"),
    path("preventivi/<int:pk>/fasi/<int:phase_id>/operazioni/aggiungi/", views.operation_add, name="operation_add"),
    path("preventivi/<int:pk>/operazioni/<int:operation_id>/rimuovi/", views.operation_delete, name="operation_delete"),
    path("preventivi/<int:pk>/fasi/<int:phase_id>/costi/aggiungi/", views.direct_cost_add, name="direct_cost_add"),
    path("preventivi/<int:pk>/costi/<int:cost_id>/rimuovi/", views.direct_cost_delete, name="direct_cost_delete"),
    path("preventivi/<int:pk>/fasi/<int:phase_id>/trattamenti/aggiungi/", views.treatment_add, name="treatment_add"),
    path("preventivi/<int:pk>/trattamenti/<int:treatment_id>/rimuovi/", views.treatment_delete, name="treatment_delete"),
    path("preventivi/<int:pk>/riepilogo/", views.quote_summary, name="summary"),
    path("preventivi/<int:pk>/completa/", views.quote_complete, name="complete"),
    path("preventivi/<int:pk>/duplica/", views.quote_duplicate, name="duplicate"),
    path("preventivi/<int:pk>/archivia/", views.quote_archive, name="archive"),
    path("preventivi/<int:pk>/pdf/", quote_pdf, name="pdf"),
]
