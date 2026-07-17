from django.contrib import admin
from django.utils.html import format_html
from .models import Client, Material, PhaseDefinition, ProductionResource


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_name", "email", "active")
    list_filter = ("active",)
    search_fields = ("name", "contact_name", "email")
    ordering = ("name",)


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("name", "current_cost_per_kg", "active")
    list_filter = ("active",)
    search_fields = ("name", "description")


@admin.register(PhaseDefinition)
class PhaseDefinitionAdmin(admin.ModelAdmin):
    list_display = ("display_order", "name", "code", "active")
    list_editable = ("active",)
    ordering = ("display_order",)


@admin.register(ProductionResource)
class ProductionResourceAdmin(admin.ModelAdmin):
    list_display = ("name", "phase", "resource_type", "hourly_cost_per_person", "cost_status", "default_operators", "active")
    list_filter = ("phase", "resource_type", "active", "user_selectable")
    search_fields = ("name", "internal_code", "notes")
    list_editable = ("hourly_cost_per_person", "default_operators", "active")
    actions = ("activate", "deactivate")

    @admin.display(description="Configurazione costo", ordering="hourly_cost_per_person")
    def cost_status(self, obj):
        if obj.cost_configured:
            return format_html('<strong style="color:#177245">Configurato</strong>')
        return format_html('<strong style="color:#b42318">Da configurare</strong>')

    @admin.action(description="Attiva risorse selezionate")
    def activate(self, request, queryset):
        queryset.update(active=True)

    @admin.action(description="Disattiva risorse selezionate")
    def deactivate(self, request, queryset):
        queryset.update(active=False)
