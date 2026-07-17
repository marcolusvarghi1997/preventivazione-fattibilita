from django.contrib import admin
from .models import DirectCost, ExternalTreatment, ItemMaterial, ItemPhase, Quote, QuoteItem, TimeOperation


class ItemInline(admin.TabularInline):
    model = QuoteItem
    extra = 0


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
    list_display = ("number", "date", "client", "status", "feasibility", "offered_price", "author", "updated_at")
    list_filter = ("status", "feasibility", "date")
    search_fields = ("number", "client__name", "items__code", "items__description")
    readonly_fields = ("number", "author", "created_at", "updated_at", "industrial_cost_display")
    inlines = (ItemInline,)

    def save_model(self, request, obj, form, change):
        if not obj.author_id:
            obj.author = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description="Costo industriale")
    def industrial_cost_display(self, obj):
        return f"EUR {obj.industrial_cost:.2f}"


@admin.register(QuoteItem)
class QuoteItemAdmin(admin.ModelAdmin):
    list_display = ("code", "quote", "quantity", "feasibility")
    list_filter = ("feasibility",)
    search_fields = ("code", "description", "quote__number")


@admin.register(ItemMaterial)
class ItemMaterialAdmin(admin.ModelAdmin):
    list_display = ("item", "material", "weight_kg", "unit_cost_snapshot")
    readonly_fields = ("unit_cost_snapshot",)


@admin.register(ItemPhase)
class ItemPhaseAdmin(admin.ModelAdmin):
    list_display = ("item", "definition", "active", "display_order")
    list_filter = ("active", "definition")


@admin.register(TimeOperation)
class TimeOperationAdmin(admin.ModelAdmin):
    list_display = ("phase", "resource_name_snapshot", "working_minutes", "setup_minutes", "operators_snapshot", "hourly_cost_snapshot")
    readonly_fields = ("resource_name_snapshot", "hourly_cost_snapshot")


admin.site.register(DirectCost)
admin.site.register(ExternalTreatment)
admin.site.site_header = "Amministrazione Preventivi Carpenteria"
admin.site.site_title = "Amministrazione"
