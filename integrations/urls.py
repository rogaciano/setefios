from django.urls import path

from . import views

app_name = "integrations"

urlpatterns = [
    path("webpic/", views.webpic_dashboard, name="webpic_dashboard"),
    path("webpic/payload/<int:pk>/", views.webpic_order_payload, name="webpic_order_payload"),
]
