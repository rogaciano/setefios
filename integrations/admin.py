from django.contrib import admin

from .models import WebpicConfiguration


@admin.register(WebpicConfiguration)
class WebpicConfigurationAdmin(admin.ModelAdmin):
    list_display = ("name", "api_company", "price_table_id", "import_products_without_price", "updated_at")
    search_fields = ("name", "api_company")
