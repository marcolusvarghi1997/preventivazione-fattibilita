from django.contrib import admin
from .admin_utils import ItalianDecimalAdminMixin
from .formatting import format_money
from .models import DirectCost, ExternalTreatment, ItemMaterial, ItemPhase, Quote, QuoteItem, TimeOperation


class ItemInline(admin.TabularInline):
    model = QuoteItem
    extra = 0


@admin.register(Quote)
class QuoteAdmin(ItalianDecimalAdminMixin, admin.ModelAdmin):
    list_display = ("number", "date", "client", "display_status_admin", "customer_decision", "feasibility", "offered_price_display", "author", "updated_at")
    list_filter = ("status", "customer_decision", "feasibility", "date")
    search_fields = ("number", "client__name", "items__code", "items__description")
    readonly_fields = ("number", "author", "created_at", "updated_at", "industrial_cost_display")
    inlines = (ItemInline,)

    def save_model(self, request, obj, form, change):
        if not obj.author_id:
            obj.author = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description="Costo industriale")
    def industrial_cost_display(self, obj):
        return format_money(obj.industrial_cost)

    @admin.display(description="Prezzo offerto", ordering="offered_price")
    def offered_price_display(self, obj):
        return format_money(obj.offered_price)

    @admin.display(description="Stato")
    def display_status_admin(self, obj):
        return obj.display_status


@admin.register(QuoteItem)
class QuoteItemAdmin(ItalianDecimalAdminMixin, admin.ModelAdmin):
    list_display = ("code", "quote", "quantity", "feasibility", "supplementary_cost_display")
    list_filter = ("feasibility",)
    search_fields = ("code", "description", "quote__number")

    @admin.display(description="Costi supplementari")
    def supplementary_cost_display(self, obj):
        return format_money(obj.supplementary_cost)


@admin.register(ItemMaterial)
class ItemMaterialAdmin(ItalianDecimalAdminMixin, admin.ModelAdmin):
    list_display = ("item", "material", "weight_kg", "unit_cost_snapshot")
    readonly_fields = ("unit_cost_snapshot",)


@admin.register(ItemPhase)
class ItemPhaseAdmin(admin.ModelAdmin):
    list_display = ("item", "definition", "active", "display_order")
    list_filter = ("active", "definition")


@admin.register(TimeOperation)
class TimeOperationAdmin(ItalianDecimalAdminMixin, admin.ModelAdmin):
    list_display = ("phase", "resource_name_snapshot", "working_minutes", "setup_minutes", "operators_snapshot", "hourly_cost_snapshot")
    readonly_fields = ("resource_name_snapshot", "hourly_cost_snapshot")


@admin.register(DirectCost)
class DirectCostAdmin(ItalianDecimalAdminMixin, admin.ModelAdmin):
    list_display = ("description", "phase", "amount")


@admin.register(ExternalTreatment)
class ExternalTreatmentAdmin(ItalianDecimalAdminMixin, admin.ModelAdmin):
    list_display = ("treatment_type", "description", "phase", "cost")
admin.site.site_header = "Amministrazione Preventivi Carpenteria"
admin.site.site_title = "Amministrazione"
