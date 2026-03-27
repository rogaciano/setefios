from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from core.models import Company, Participant, ParticipantCompany, Supplier
from sales.models import Category, Color, FabricRoll, Order, OrderItem, OrderStatus, Product, ProductUnit, StockEntry

from .models import WebpicConfiguration
from .services import WebpicService


class WebpicServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="tester",
            password="senha123456",
            full_name="Usuario Teste",
        )
        self.client_company = Company.objects.create(
            legal_name="CLIENTE TESTE LTDA",
            trade_name="Cliente Teste",
            cnpj="12.345.678/0001-99",
            state_registration="123456789",
            phone="(85) 99999-0000",
            email="cliente@teste.local",
            street="Rua A",
            number="123",
            district="Centro",
            postal_code="60000-000",
            city="Fortaleza",
            state="CE",
        )
        self.contact = Participant.objects.create(name="MARIA TESTE")
        ParticipantCompany.objects.create(
            participant=self.contact,
            company=self.client_company,
            is_primary=True,
        )
        self.representative = Participant.objects.create(
            name="REP TESTE",
            is_representative=True,
        )
        self.category = Category.objects.create(name="TECIDOS")
        self.color = Color.objects.create(name="PRETO")
        self.product = Product.objects.create(
            category=self.category,
            reference="REF-1",
            description="TECIDO TESTE",
            price=Decimal("120.00"),
            unit=ProductUnit.METER,
            created_by=self.user,
        )
        self.product.colors.add(self.color)
        self.product.sync_variants()
        self.variant = self.product.variants.get()
        self.variant.barcode = "7890001112223"
        self.variant.save(update_fields=["barcode", "updated_at"])
        self.supplier = Supplier.objects.create(
            trade_name="FORNECEDOR TESTE",
            cnpj="98.765.432/0001-10",
            city="Fortaleza",
            state="CE",
        )
        self.stock_entry = StockEntry.objects.create(
            supplier=self.supplier,
            created_by=self.user,
            notes="Entrada de teste",
        )
        self.roll = FabricRoll.objects.create(
            stock_entry=self.stock_entry,
            variant=self.variant,
            initial_quantity=Decimal("10.000"),
            notes="Rolo para teste",
        )
        self.order = Order.objects.create(
            buyer_company=self.client_company,
            participant=self.contact,
            representative=self.representative,
            status="confirmed",
            payment_method="PIX",
            discount_type="P",
            discount_value=Decimal("10.00"),
            created_by=self.user,
        )
        OrderItem.objects.create(
            order=self.order,
            roll=self.roll,
            variant=self.variant,
            quantity=Decimal("2.000"),
            unit_price=Decimal("120.00"),
        )
        self.order.recalculate_totals()
        FabricRoll.refresh_many([self.roll.pk])
        self.config = WebpicConfiguration.get_solo()
        self.config.api_company = "1"
        self.config.api_token = "token-webpic"
        self.config.price_table_id = 10
        self.config.employee_id = 20
        self.config.representative_id = 30
        self.config.client_group_id = 40
        self.config.current_account_id = 50
        self.config.save()

    def test_build_order_payload_uses_roll_variant_barcode(self):
        payload = WebpicService(self.config).build_order_payload(self.order)

        self.assertEqual(payload["Codigo"], str(self.order.pk))
        self.assertEqual(payload["Cliente"]["RazaoSocial"], "CLIENTE TESTE LTDA")
        self.assertEqual(payload["Cliente"]["CpfCnpj"], "12345678000199")
        self.assertEqual(payload["Produtos"][0]["Codigo"], "7890001112223")
        self.assertEqual(payload["Produtos"][0]["Quantidade"], 2.0)
        self.assertEqual(payload["Desconto"], 24.0)
        self.assertEqual(payload["Pagamentos"][0]["ValorPago"], float(self.order.total_amount))



    def test_pending_orders_exports_only_confirmed_orders(self):
        reserved_order = Order.objects.create(
            buyer_company=self.client_company,
            participant=self.contact,
            representative=self.representative,
            status=OrderStatus.RESERVED,
            created_by=self.user,
        )
        draft_order = Order.objects.create(
            buyer_company=self.client_company,
            participant=self.contact,
            representative=self.representative,
            status=OrderStatus.DRAFT,
            created_by=self.user,
        )
        for extra_order in (reserved_order, draft_order):
            OrderItem.objects.create(
                order=extra_order,
                roll=self.roll,
                variant=self.variant,
                quantity=Decimal("1.000"),
                unit_price=Decimal("120.00"),
            )

        pending_ids = list(WebpicService(self.config).pending_orders().values_list("pk", flat=True))

        self.assertEqual(pending_ids, [self.order.pk])

    def test_sync_remote_products_creates_variants_and_barcodes(self):
        remote_products = [
            {
                "Referencia": "AB 100",
                "Descricao": "Tecido encorpado",
                "Grupo": "Tecidos",
                "Unidade": "KG",
                "Grades": [
                    {
                        "Cor": "Azul",
                        "CodigoBarras": "111",
                        "Valor": "89.90",
                    },
                    {
                        "Cor": "Preto",
                        "CodigoBarras": "222",
                        "Valor": "99.90",
                    },
                ],
            }
        ]

        result = WebpicService(self.config).sync_remote_products(remote_products, user=self.user)
        imported_product = Product.objects.get(reference="AB100")

        self.assertEqual(len(result["imported"]), 1)
        self.assertEqual(result["report"]["total_rows"], 1)
        self.assertEqual(result["report"]["imported_total"], 1)
        self.assertEqual(result["report"]["updated_total"], 0)
        self.assertEqual(result["report"]["skipped_total"], 0)
        self.assertEqual(imported_product.category.name, "TECIDOS")
        self.assertEqual(imported_product.price, Decimal("99.90"))
        self.assertEqual(imported_product.unit, ProductUnit.KILOGRAM)
        self.assertEqual(imported_product.variants.count(), 2)
        self.assertEqual(
            imported_product.variants.get(color__name="AZUL").barcode,
            "111",
        )

    def test_sync_remote_products_reports_zero_price_and_missing_grades(self):
        remote_products = [
            {
                "Referencia": "AB 100",
                "Descricao": "Tecido encorpado",
                "Grupo": "Tecidos",
                "Grades": [
                    {
                        "Cor": "Azul",
                        "CodigoBarras": "111",
                        "Valor": "89.90",
                    }
                ],
            },
            {
                "Referencia": "ZERO-1",
                "Descricao": "Sem preco",
                "Grupo": "Tecidos",
                "Grades": [
                    {
                        "Cor": "Preto",
                        "CodigoBarras": "222",
                        "Valor": "0.00",
                    }
                ],
            },
            {
                "Referencia": "GRADE-0",
                "Descricao": "Sem grade",
                "Grupo": "Tecidos",
                "Grades": [],
            },
        ]

        result = WebpicService(self.config).sync_remote_products(remote_products, user=self.user)

        self.assertEqual(result["report"]["total_rows"], 3)
        self.assertEqual(result["report"]["processed_total"], 1)
        self.assertEqual(result["report"]["imported_total"], 1)
        self.assertEqual(result["report"]["updated_total"], 0)
        self.assertEqual(result["report"]["processed_without_price_total"], 0)
        self.assertEqual(result["report"]["skipped_total"], 2)
        self.assertEqual(result["report"]["skipped_no_price"], 1)
        self.assertEqual(result["report"]["skipped_no_grades"], 1)
        self.assertEqual(result["report"]["skipped_missing_reference"], 0)

    def test_sync_remote_products_can_import_zero_price_when_configured(self):
        self.config.import_products_without_price = True
        self.config.save(update_fields=["import_products_without_price", "updated_at"])
        remote_products = [
            {
                "Referencia": "ZERO-2",
                "Descricao": "Produto sem preco",
                "Grupo": "Tecidos",
                "Grades": [
                    {
                        "Cor": "Preto",
                        "CodigoBarras": "222",
                        "Valor": "0.00",
                    }
                ],
            }
        ]

        result = WebpicService(self.config).sync_remote_products(remote_products, user=self.user)
        imported_product = Product.objects.get(reference="ZERO-2")

        self.assertEqual(result["report"]["processed_total"], 1)
        self.assertEqual(result["report"]["imported_total"], 1)
        self.assertEqual(result["report"]["processed_without_price_total"], 1)
        self.assertEqual(result["report"]["skipped_no_price"], 0)
        self.assertEqual(imported_product.price, Decimal("0.00"))
        self.assertEqual(imported_product.variants.count(), 1)

    def test_sync_remote_products_keeps_existing_price_when_row_has_no_price(self):
        self.config.import_products_without_price = True
        self.config.save(update_fields=["import_products_without_price", "updated_at"])
        remote_products = [
            {
                "Referencia": "REF-1",
                "Descricao": "TECIDO TESTE ATUALIZADO",
                "Grupo": "Tecidos",
                "Grades": [
                    {
                        "Cor": "Preto",
                        "CodigoBarras": "999",
                        "Valor": "0.00",
                    }
                ],
            }
        ]

        result = WebpicService(self.config).sync_remote_products(remote_products, user=self.user)
        self.product.refresh_from_db()
        self.variant.refresh_from_db()

        self.assertEqual(result["report"]["updated_total"], 1)
        self.assertEqual(result["report"]["processed_without_price_total"], 1)
        self.assertEqual(self.product.price, Decimal("120.00"))
        self.assertEqual(self.product.description, "TECIDO TESTE ATUALIZADO")
        self.assertEqual(self.variant.barcode, "999")

