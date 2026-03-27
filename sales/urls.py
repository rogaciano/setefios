from django.urls import path

from . import views

app_name = "sales"

urlpatterns = [
    path("produtos/", views.product_list, name="product_list"),
    path("produtos/novo/", views.product_form, name="product_create"),
    path("produtos/<int:pk>/editar/", views.product_form, name="product_update"),
    path("estoque/movimentacoes/", views.stock_movement_list, name="stock_movement_list"),
    path("estoque/", views.stock_overview, name="stock_overview"),
    path("rolos/buscar/", views.roll_lookup, name="roll_lookup"),
    path("rolos/<int:roll_pk>/ajustar/", views.stock_adjustment_form, name="stock_adjustment_create"),
    path("entradas/", views.stock_entry_list, name="stock_entry_list"),
    path("entradas/importar/", views.stock_entry_import, name="stock_entry_import"),
    path("entradas/nova/", views.stock_entry_form, name="stock_entry_create"),
    path("entradas/<int:pk>/editar/", views.stock_entry_form, name="stock_entry_update"),
    path("entradas/<int:pk>/etiquetas/", views.stock_entry_labels, name="stock_entry_labels"),
    path("rolos/<int:pk>/etiqueta/", views.roll_label, name="roll_label"),
    path("pedidos/", views.order_list, name="order_list"),
    path("pedidos/novo/", views.order_form, name="order_create"),
    path("pedidos/<int:pk>/editar/", views.order_form, name="order_update"),
]
