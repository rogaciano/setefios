from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class SalesUserAdmin(UserAdmin):
    list_display = ("username", "full_name", "email", "is_active", "is_staff")
    search_fields = ("username", "full_name", "email")
    list_filter = ("is_active", "is_staff", "is_superuser")
    fieldsets = UserAdmin.fieldsets + (
        (
            "Contexto do sistema",
            {
                "fields": (
                    "full_name",
                    "last_access_at",
                    "last_ip",
                )
            },
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Contexto do sistema",
            {"fields": ("full_name", "email")},
        ),
    )
