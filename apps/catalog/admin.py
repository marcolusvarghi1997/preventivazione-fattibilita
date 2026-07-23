from django import forms
from django.contrib import admin
from django.utils.html import format_html
from apps.quotes.admin_utils import ItalianDecimalAdminMixin
from apps.quotes.formatting import format_money
from .models import Client, ClientContact, Material, PhaseDefinition, ProductionResource, SiteConfiguration


class ClientContactInline(admin.TabularInline):
    model = ClientContact
    extra = 1


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_name", "email", "active")
    list_filter = ("active",)
    search_fields = ("name", "contact_name", "email")
    ordering = ("name",)
    inlines = (ClientContactInline,)


@admin.register(ClientContact)
class ClientContactAdmin(admin.ModelAdmin):
    list_display = ("name", "client", "email", "phone", "active")
    list_filter = ("active",)
    search_fields = ("name", "email", "client__name")
    autocomplete_fields = ("client",)


@admin.register(Material)
class MaterialAdmin(ItalianDecimalAdminMixin, admin.ModelAdmin):
    list_display = ("name", "current_cost_display", "active")
    list_filter = ("active",)
    search_fields = ("name", "description")

    @admin.display(description="Costo corrente al kg", ordering="current_cost_per_kg")
    def current_cost_display(self, obj):
        return format_money(obj.current_cost_per_kg)


@admin.register(PhaseDefinition)
class PhaseDefinitionAdmin(admin.ModelAdmin):
    list_display = ("display_order", "name", "code", "active")
    list_editable = ("active",)
    ordering = ("display_order",)


@admin.register(ProductionResource)
class ProductionResourceAdmin(ItalianDecimalAdminMixin, admin.ModelAdmin):
    list_display = ("name", "phase", "resource_type", "hourly_cost_per_person", "cost_status", "default_operators", "active")
    list_filter = ("phase", "resource_type", "active", "user_selectable")
    search_fields = ("name", "internal_code", "notes")
    list_editable = ("hourly_cost_per_person", "default_operators", "active")
    actions = ("activate", "deactivate")

    @admin.display(description="Configurazione costo", ordering="hourly_cost_per_person")
    def cost_status(self, obj):
        if obj.cost_configured:
            return format_html('<strong class="admin-status admin-status--ok">Configurato</strong>')
        return format_html('<strong class="admin-status admin-status--warning">Da configurare</strong>')

    @admin.action(description="Attiva risorse selezionate")
    def activate(self, request, queryset):
        queryset.update(active=True)

    @admin.action(description="Disattiva risorse selezionate")
    def deactivate(self, request, queryset):
        queryset.update(active=False)


class SiteConfigurationAdminForm(forms.ModelForm):
    class Meta:
        model = SiteConfiguration
        fields = "__all__"
        widgets = {
            "primary_color": forms.TextInput(attrs={"type": "color"}),
            "accent_color": forms.TextInput(attrs={"type": "color"}),
        }


@admin.register(SiteConfiguration)
class SiteConfigurationAdmin(admin.ModelAdmin):
    form = SiteConfigurationAdminForm
    fieldsets = (
        ("Identità visiva", {"fields": ("site_title", "company_name", "logo", "favicon", "primary_color", "accent_color")}),
        ("Dati aziendali per i PDF", {"fields": ("address", "vat", "email", "phone", "terms")}),
        ("Rete locale", {"fields": ("lan_enabled", "updated_at"), "description": "L'impostazione ha effetto immediato e non richiede script o riavvii."}),
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not SiteConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
