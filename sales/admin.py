from django.contrib import admin

from .models import (
    Category,
    Color,
    FabricRoll,
    Order,
    OrderItem,
    Product,
    ProductVariant,
    StockAdjustment,
    StockEntry,
    StockMovement,
)


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("reference", "description", "category", "unit", "price", "is_active")
    list_filter = ("category", "unit", "is_active")
    search_fields = ("reference", "description")
    inlines = [ProductVariantInline]
    filter_horizontal = ("colors",)


class FabricRollInline(admin.TabularInline):
    model = FabricRoll
    extra = 0
    readonly_fields = ("identifier",)


@admin.register(StockEntry)
class StockEntryAdmin(admin.ModelAdmin):
    list_display = ("pk", "supplier", "source_note_number", "received_at", "created_by", "created_at")
    list_filter = ("received_at", "supplier")
    search_fields = ("supplier__trade_name", "source_note_number", "notes")
    inlines = [FabricRollInline]


@admin.register(FabricRoll)
class FabricRollAdmin(admin.ModelAdmin):
    list_display = (
        "identifier",
        "variant",
        "stock_entry",
        "initial_quantity",
        "available_quantity",
        "created_at",
    )
    list_filter = ("stock_entry__supplier", "variant__product")
    search_fields = (
        "identifier",
        "variant__product__reference",
        "variant__product__description",
        "variant__color__name",
    )


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("pk", "roll", "adjustment_type", "quantity", "created_by", "created_at")
    list_filter = ("adjustment_type", "roll__stock_entry__supplier")
    search_fields = ("roll__identifier", "roll__variant__product__reference", "notes")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("pk", "roll", "movement_type", "quantity", "balance_after", "effective_at")
    list_filter = ("movement_type", "roll__stock_entry__supplier")
    search_fields = ("roll__identifier", "roll__variant__product__reference")
    readonly_fields = (
        "roll",
        "movement_type",
        "quantity",
        "balance_after",
        "stock_entry",
        "stock_adjustment",
        "order",
        "order_item",
        "effective_at",
    )


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "buyer_company",
        "participant",
        "status",
        "webpic_integrated",
        "total_amount",
        "created_at",
    )
    list_filter = ("status", "buyer_company", "webpic_integrated")
    search_fields = ("pk", "buyer_company__legal_name", "participant__name")
    readonly_fields = ("webpic_payload", "webpic_response", "webpic_exported_at")
    inlines = [OrderItemInline]


admin.site.register(Category)
admin.site.register(Color)
admin.site.register(ProductVariant)
admin.site.register(OrderItem)
