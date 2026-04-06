from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from .models import Company


class ClientViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="cliente_view",
            password="senha123456",
            full_name="Cliente View",
        )
        self.client.force_login(self.user)
        self.company = Company.objects.create(
            legal_name="CLIENTE BASE LTDA",
            trade_name="Cliente Base",
            cnpj="10.000.000/0001-10",
            city="Fortaleza",
            state="CE",
            is_active=True,
        )

    def test_client_list_shows_registered_client(self):
        response = self.client.get(reverse("core:client_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cadastro de clientes")
        self.assertContains(response, "CLIENTE BASE LTDA")

    def test_client_update_persists_changes(self):
        response = self.client.post(
            reverse("core:client_update", args=[self.company.pk]),
            {
                "legal_name": "CLIENTE BASE ATUALIZADO LTDA",
                "trade_name": "Cliente Atualizado",
                "cnpj": "10.000.000/0001-10",
                "state_registration": "123456",
                "phone": "(85) 99999-0000",
                "email": "compras@cliente.local",
                "street": "Rua A",
                "number": "123",
                "complement": "Sala 2",
                "district": "Centro",
                "postal_code": "60000-000",
                "city": "Juazeiro do Norte",
                "state": "CE",
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("core:client_list"))
        self.company.refresh_from_db()
        self.assertEqual(self.company.legal_name, "CLIENTE BASE ATUALIZADO LTDA")
        self.assertEqual(self.company.trade_name, "Cliente Atualizado")
        self.assertEqual(self.company.email, "compras@cliente.local")
        self.assertEqual(self.company.city, "Juazeiro do Norte")
