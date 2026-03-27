from django.contrib import admin

from .models import Company, Participant, ParticipantCompany, Supplier


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("trade_name", "legal_name", "cnpj", "city", "state", "is_active")
    search_fields = ("trade_name", "legal_name", "cnpj")
    list_filter = ("is_active", "state")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("trade_name", "cnpj", "contact_name", "city", "state", "is_active")
    search_fields = ("trade_name", "cnpj", "contact_name")
    list_filter = ("is_active", "state")


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone", "is_representative", "is_active")
    search_fields = ("name", "email", "phone")
    list_filter = ("is_representative", "is_active")


admin.site.register(ParticipantCompany)
