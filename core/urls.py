from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("clientes/", views.client_list, name="client_list"),
    path("clientes/novo/", views.client_form, name="client_create"),
    path("clientes/<int:pk>/editar/", views.client_form, name="client_update"),
    path("clientes/<int:client_pk>/contatos/", views.client_participants, name="client_participants"),
    path("contatos/", views.participant_list, name="participant_list"),
    path("contatos/novo/", views.participant_form, name="participant_create"),
    path("contatos/<int:pk>/editar/", views.participant_form, name="participant_update"),
    path("fornecedores/", views.supplier_list, name="supplier_list"),
    path("fornecedores/novo/", views.supplier_form, name="supplier_create"),
    path("fornecedores/<int:pk>/editar/", views.supplier_form, name="supplier_update"),
]
