from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("fornecedores/", views.supplier_list, name="supplier_list"),
    path("fornecedores/novo/", views.supplier_form, name="supplier_create"),
    path("fornecedores/<int:pk>/editar/", views.supplier_form, name="supplier_update"),
]
