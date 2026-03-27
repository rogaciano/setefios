from decimal import Decimal
import json
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from core.models import Company, Participant, ParticipantCompany, Supplier, SupplierImportProfile

from .models import Category, Color, FabricRoll, Order, OrderItem, OrderStatus, Product, ProductUnit, StockAdjustment, StockAdjustmentType, StockEntry, StockMovementType


class FabricRollReservationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="estoque",
            password="senha123456",
            full_name="Usuario Estoque",
        )
        self.company = Company.objects.create(
            legal_name="CLIENTE ESTOQUE LTDA",
            trade_name="Cliente Estoque",
            cnpj="10.000.000/0001-10",
            city="Fortaleza",
            state="CE",
        )
        self.contact = Participant.objects.create(name="CONTATO ESTOQUE")
        ParticipantCompany.objects.create(
            participant=self.contact,
            company=self.company,
            is_primary=True,
        )
        self.category = Category.objects.create(name="TECIDOS")
        self.color = Color.objects.create(name="VERDE")
        self.product = Product.objects.create(
            category=self.category,
            reference="TEC-EST-1",
            description="TECIDO ESTOQUE",
            price=Decimal("50.00"),
            unit=ProductUnit.METER,
            created_by=self.user,
        )
        self.product.colors.add(self.color)
        self.product.sync_variants()
        self.variant = self.product.variants.get()
        self.supplier = Supplier.objects.create(
            trade_name="FORNECEDOR ESTOQUE",
            cnpj="20.000.000/0001-20",
            city="Fortaleza",
            state="CE",
        )
        self.entry = StockEntry.objects.create(
            supplier=self.supplier,
            created_by=self.user,
        )
        self.roll = FabricRoll.objects.create(
            stock_entry=self.entry,
            variant=self.variant,
            initial_quantity=Decimal("10.000"),
        )

    def test_roll_availability_only_counts_reserved_and_confirmed_orders(self):
        draft_order = Order.objects.create(
            buyer_company=self.company,
            participant=self.contact,
            status=OrderStatus.DRAFT,
            created_by=self.user,
        )
        reserved_order = Order.objects.create(
            buyer_company=self.company,
            participant=self.contact,
            status=OrderStatus.RESERVED,
            created_by=self.user,
        )
        confirmed_order = Order.objects.create(
            buyer_company=self.company,
            participant=self.contact,
            status=OrderStatus.CONFIRMED,
            created_by=self.user,
        )
        cancelled_order = Order.objects.create(
            buyer_company=self.company,
            participant=self.contact,
            status=OrderStatus.CANCELLED,
            created_by=self.user,
        )

        OrderItem.objects.create(
            order=draft_order,
            roll=self.roll,
            variant=self.variant,
            quantity=Decimal("1.000"),
            unit_price=Decimal("50.00"),
        )
        OrderItem.objects.create(
            order=reserved_order,
            roll=self.roll,
            variant=self.variant,
            quantity=Decimal("2.000"),
            unit_price=Decimal("50.00"),
        )
        confirmed_item = OrderItem.objects.create(
            order=confirmed_order,
            roll=self.roll,
            variant=self.variant,
            quantity=Decimal("2.500"),
            unit_price=Decimal("50.00"),
        )
        OrderItem.objects.create(
            order=cancelled_order,
            roll=self.roll,
            variant=self.variant,
            quantity=Decimal("3.000"),
            unit_price=Decimal("50.00"),
        )

        self.assertEqual(confirmed_item.variant_id, self.variant.pk)
        self.assertEqual(self.roll.reserved_quantity(), Decimal("4.500"))
        self.assertEqual(self.roll.sellable_quantity(), Decimal("5.500"))

        self.roll.refresh_availability()
        self.roll.refresh_from_db()
        self.assertEqual(self.roll.available_quantity, Decimal("5.500"))

        movements = list(self.roll.movements.order_by("effective_at", "pk"))
        self.assertEqual(
            [movement.movement_type for movement in movements],
            [
                StockMovementType.ENTRY,
                StockMovementType.RESERVED,
                StockMovementType.CONFIRMED,
            ],
        )
        self.assertEqual(
            [movement.balance_after for movement in movements],
            [Decimal("10.000"), Decimal("8.000"), Decimal("5.500")],
        )


class StockEntryViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="entrada",
            password="senha123456",
            full_name="Usuario Entrada",
        )
        self.client.force_login(self.user)
        self.supplier = Supplier.objects.create(
            trade_name="FORNECEDOR ENTRADA",
            cnpj="30.000.000/0001-30",
            city="Fortaleza",
            state="CE",
        )
        self.category = Category.objects.create(name="MALHAS")
        self.preto = Color.objects.create(name="PRETO")
        self.off_white = Color.objects.create(name="OFF WHITE")
        self.product = Product.objects.create(
            category=self.category,
            reference="TEC-ENT-1",
            description="VISCOSE",
            price=Decimal("70.00"),
            unit=ProductUnit.KILOGRAM,
            created_by=self.user,
        )
        self.product.colors.add(self.preto, self.off_white)
        self.product.sync_variants()
        self.variant_preto = self.product.variants.get(color=self.preto)
        self.variant_off_white = self.product.variants.get(color=self.off_white)

    def test_stock_entry_create_groups_rolls_inside_product_row(self):
        payload = json.dumps(
            [
                {
                    "variant_id": self.variant_preto.pk,
                    "quantity": "12.500",
                    "notes": "Rolo 1",
                },
                {
                    "variant_id": self.variant_preto.pk,
                    "quantity": "8.250",
                    "notes": "Rolo 2",
                },
                {
                    "variant_id": self.variant_off_white.pk,
                    "quantity": "5.000",
                    "notes": "Rolo 3",
                },
            ]
        )

        response = self.client.post(
            reverse("sales:stock_entry_create"),
            {
                "supplier": self.supplier.pk,
                "received_at": "2026-03-26",
                "notes": "Entrada agrupada",
                "rows-TOTAL_FORMS": "8",
                "rows-INITIAL_FORMS": "0",
                "rows-MIN_NUM_FORMS": "0",
                "rows-MAX_NUM_FORMS": "1000",
                "rows-0-product": str(self.product.pk),
                "rows-0-rolls_payload": payload,
            },
        )

        self.assertEqual(response.status_code, 302)
        entry = StockEntry.objects.get(notes="Entrada agrupada")
        rolls = entry.rolls.select_related("variant__color").order_by("pk")

        self.assertEqual(rolls.count(), 3)
        self.assertEqual(
            rolls.filter(variant=self.variant_preto).count(),
            2,
        )
        self.assertEqual(
            rolls.filter(variant=self.variant_off_white).count(),
            1,
        )
        self.assertEqual(
            rolls.filter(variant=self.variant_preto).first().available_quantity,
            Decimal("12.500"),
        )
        self.assertTrue(all(roll.identifier.startswith("ROL") for roll in rolls))

    def test_stock_entry_edit_renders_iso_value_in_date_input(self):
        entry = StockEntry.objects.create(
            supplier=self.supplier,
            received_at="2026-03-27",
            notes="Entrada com data",
            created_by=self.user,
        )

        response = self.client.get(reverse("sales:stock_entry_update", args=[entry.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="date"')
        self.assertContains(response, 'value="2026-03-27"')


class PurchaseImportViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="importador_entrada",
            password="senha123456",
            full_name="Importador Entrada",
        )
        self.client.force_login(self.user)
        self.docs_dir = Path(settings.BASE_DIR) / "docs"
        self.supplier = Supplier.objects.create(
            trade_name="THAMI TEX MALHAS LTDA",
            cnpj="40.000.000/0001-40",
            city="Fortaleza",
            state="CE",
        )
        self.category = Category.objects.create(name="TECIDOS IMPORTADOS")
        self.amarelo = Color.objects.create(name="AMARELO BB")
        self.preto = Color.objects.create(name="PRETO")
        self.verde = Color.objects.create(name="VERDE MUSGO")
        self.product = Product.objects.create(
            category=self.category,
            reference="0010121",
            description="MADRI PROTECAO UV",
            price=Decimal("10.00"),
            unit=ProductUnit.KILOGRAM,
            created_by=self.user,
        )
        self.product.colors.add(self.amarelo, self.preto, self.verde)
        self.product.sync_variants()
        self.variant_preto = self.product.variants.get(color=self.preto)

    def _upload_purchase_document(self, file_name):
        file_bytes = (self.docs_dir / file_name).read_bytes()
        uploaded = SimpleUploadedFile(
            file_name,
            file_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        response = self.client.post(
            reverse("sales:stock_entry_import"),
            {
                "action": "upload",
                "document": uploaded,
            },
        )

        self.assertRedirects(response, reverse("sales:stock_entry_import"))
        return self.client.session["stock_entry_import_preview"]

    def _build_import_draft_post_data(self, draft):
        payload = {
            "supplier": str(self.supplier.pk),
            "received_at": draft["received_at"],
            "notes": draft["notes"],
            "rows-TOTAL_FORMS": str(len(draft["rows"])),
            "rows-INITIAL_FORMS": str(len(draft["rows"])),
            "rows-MIN_NUM_FORMS": "0",
            "rows-MAX_NUM_FORMS": "1000",
        }
        for index, row in enumerate(draft["rows"]):
            payload[f"rows-{index}-product"] = str(row["product"])
            payload[f"rows-{index}-rolls_payload"] = row["rolls_payload"]
        return payload

    def _create_imported_entry(self, file_name="008131.xlsx"):
        preview = self._upload_purchase_document(file_name)
        response = self.client.post(
            reverse("sales:stock_entry_import"),
            {"action": "apply"},
        )
        self.assertRedirects(response, reverse("sales:stock_entry_create"))
        form_response = self.client.get(reverse("sales:stock_entry_create"))
        self.assertEqual(form_response.status_code, 200)

        save_response = self.client.post(
            reverse("sales:stock_entry_create"),
            self._build_import_draft_post_data(preview["draft"]),
        )

        created_entry = StockEntry.objects.latest("pk")
        self.assertRedirects(save_response, reverse("sales:stock_entry_update", args=[created_entry.pk]))
        return preview, form_response, created_entry

    def test_upload_purchase_document_prefills_stock_entry_draft(self):
        file_bytes = (self.docs_dir / "008131.xlsx").read_bytes()
        uploaded = SimpleUploadedFile(
            "008131.xlsx",
            file_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        response = self.client.post(
            reverse("sales:stock_entry_import"),
            {
                "action": "upload",
                "document": uploaded,
            },
        )

        self.assertRedirects(response, reverse("sales:stock_entry_import"))
        preview = self.client.session["stock_entry_import_preview"]
        self.assertTrue(preview["can_apply"])
        self.assertEqual(preview["suggested_supplier_id"], self.supplier.pk)
        self.assertEqual(preview["ready_total"], 1)
        self.assertEqual(preview["product_total"], 1)

        response = self.client.post(
            reverse("sales:stock_entry_import"),
            {"action": "apply"},
        )

        self.assertRedirects(response, reverse("sales:stock_entry_create"))
        response = self.client.get(reverse("sales:stock_entry_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Entrada montada a partir de 008131.xlsx")
        self.assertEqual(response.context["form"].initial["supplier"], self.supplier.pk)
        self.assertEqual(response.context["imported_draft"]["note_number"], "008131")
        self.assertEqual(response.context["formset"].initial[0]["product"], self.product.pk)
        self.assertIn(str(self.variant_preto.pk), response.context["formset"].initial[0]["rolls_payload"])

        save_response = self.client.post(
            reverse("sales:stock_entry_create"),
            {
                "supplier": str(self.supplier.pk),
                "received_at": response.context["form"].initial["received_at"],
                "notes": response.context["form"].initial["notes"],
                "rows-TOTAL_FORMS": str(len(response.context["formset"].forms)),
                "rows-INITIAL_FORMS": str(response.context["formset"].initial_form_count()),
                "rows-MIN_NUM_FORMS": "0",
                "rows-MAX_NUM_FORMS": "1000",
                "rows-0-product": str(self.product.pk),
                "rows-0-rolls_payload": response.context["formset"].initial[0]["rolls_payload"],
            },
        )

        created_entry = StockEntry.objects.latest("pk")
        self.assertRedirects(save_response, reverse("sales:stock_entry_update", args=[created_entry.pk]))
        self.assertEqual(created_entry.source_note_number, "008131")
        profile = SupplierImportProfile.objects.get(supplier=self.supplier)
        self.assertEqual(profile.parser_key, "FATURAMENTO_XLSX_BASIC")
        self.assertEqual(profile.supplier_hint_pattern, "THAMI TEX MALHAS LTDA")
        self.assertEqual(profile.match_count, 1)

    def test_duplicate_purchase_document_is_blocked_in_preview_and_on_save(self):
        _preview, _form_response, created_entry = self._create_imported_entry()

        duplicate_preview = self._upload_purchase_document("008131.xlsx")
        self.assertFalse(duplicate_preview["can_apply"])
        self.assertEqual(duplicate_preview["duplicate_check"]["status"], "exact")
        self.assertEqual(duplicate_preview["duplicate_check"]["entry_id"], created_entry.pk)

        session = self.client.session
        session["stock_entry_import_draft"] = duplicate_preview["draft"]
        session.save()

        response = self.client.post(
            reverse("sales:stock_entry_create"),
            self._build_import_draft_post_data(duplicate_preview["draft"]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "mesmos produtos e totais")
        self.assertEqual(StockEntry.objects.count(), 1)

    def test_import_preview_lists_document_colors_for_missing_reference(self):
        preview = self._upload_purchase_document("DANIEL - 921316.xlsx")
        item = preview["items"][0]

        self.assertFalse(item["product_exists"])
        self.assertEqual(item["reference"], "00139000000-000")
        self.assertEqual(item["color_total"], 4)
        self.assertEqual(item["document_colors"][0]["code"], "4050")
        self.assertEqual(item["document_colors"][0]["name"], "VERDE TW")
        self.assertEqual(item["document_colors"][0]["total_quantity"], "194.700")
        self.assertEqual(item["document_colors"][0]["roll_total"], 11)
        self.assertEqual(item["document_colors"][1]["name"], "PIMENTA (RUBI)")

        response = self.client.get(reverse("sales:stock_entry_import"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cores detectadas")
        self.assertContains(response, "VERDE TW")
        self.assertContains(response, "PIMENTA (RUBI)")
        self.assertContains(response, "Cor 7000")

    def test_supplier_profile_guides_recognition_for_known_layout(self):
        supplier = Supplier.objects.create(
            trade_name="LIATHU TECIDOS",
            cnpj="40.000.000/0001-41",
            city="Fortaleza",
            state="CE",
        )
        SupplierImportProfile.objects.create(
            supplier=supplier,
            name="Daniel faturamento",
            parser_key="FATURAMENTO_XLSX_LOTE",
            supplier_hint_pattern="DEMONSTRACAO LIATHU",
        )

        file_bytes = (self.docs_dir / "DANIEL - 921316.xlsx").read_bytes()
        uploaded = SimpleUploadedFile(
            "DANIEL - 921316.xlsx",
            file_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        response = self.client.post(
            reverse("sales:stock_entry_import"),
            {
                "action": "upload",
                "document": uploaded,
            },
        )

        self.assertRedirects(response, reverse("sales:stock_entry_import"))
        preview = self.client.session["stock_entry_import_preview"]
        self.assertEqual(preview["suggested_supplier_id"], supplier.pk)
        self.assertTrue(preview["matched_by_profile"])
        self.assertEqual(preview["matched_profile_label"], "DANIEL FATURAMENTO")


class StockOverviewViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="consulta_estoque",
            password="senha123456",
            full_name="Consulta Estoque",
        )
        self.client.force_login(self.user)
        self.company = Company.objects.create(
            legal_name="CLIENTE ESTOQUE VIEW LTDA",
            trade_name="Cliente Estoque View",
            cnpj="60.000.000/0001-60",
            city="Fortaleza",
            state="CE",
        )
        self.contact = Participant.objects.create(name="CONTATO VIEW")
        ParticipantCompany.objects.create(
            participant=self.contact,
            company=self.company,
            is_primary=True,
        )
        self.supplier = Supplier.objects.create(
            trade_name="FORNECEDOR ESTOQUE VIEW",
            cnpj="50.000.000/0001-50",
            city="Fortaleza",
            state="CE",
        )
        self.category = Category.objects.create(name="MALHAS VIEW")
        self.color = Color.objects.create(name="AZUL")
        self.product = Product.objects.create(
            category=self.category,
            reference="TEC-STK-1",
            description="MALHA TESTE",
            price=Decimal("45.00"),
            unit=ProductUnit.KILOGRAM,
            created_by=self.user,
        )
        self.product.colors.add(self.color)
        self.product.sync_variants()
        self.variant = self.product.variants.get()
        self.entry = StockEntry.objects.create(
            supplier=self.supplier,
            created_by=self.user,
        )
        self.roll_available = FabricRoll.objects.create(
            stock_entry=self.entry,
            variant=self.variant,
            initial_quantity=Decimal("10.000"),
        )
        self.roll_reserved = FabricRoll.objects.create(
            stock_entry=self.entry,
            variant=self.variant,
            initial_quantity=Decimal("10.000"),
        )
        self.roll_sold_out = FabricRoll.objects.create(
            stock_entry=self.entry,
            variant=self.variant,
            initial_quantity=Decimal("5.000"),
        )
        self.order = Order.objects.create(
            buyer_company=self.company,
            participant=self.contact,
            status="confirmed",
            created_by=self.user,
        )
        OrderItem.objects.create(
            order=self.order,
            roll=self.roll_reserved,
            variant=self.variant,
            quantity=Decimal("4.000"),
            unit_price=Decimal("45.00"),
        )
        OrderItem.objects.create(
            order=self.order,
            roll=self.roll_sold_out,
            variant=self.variant,
            quantity=Decimal("5.000"),
            unit_price=Decimal("45.00"),
        )
        FabricRoll.refresh_many([self.roll_available.pk, self.roll_reserved.pk, self.roll_sold_out.pk])

    def test_stock_overview_shows_consolidated_and_roll_balances(self):
        response = self.client.get(reverse("sales:stock_overview"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["roll_total"], 3)
        self.assertEqual(response.context["summary"]["available_roll_total"], 2)
        self.assertEqual(response.context["summary"]["reserved_roll_total"], 1)
        self.assertEqual(response.context["summary"]["sold_out_roll_total"], 1)
        self.assertEqual(len(response.context["variant_rows"]), 1)
        self.assertEqual(response.context["variant_rows"][0]["available_total"], Decimal("16.000"))
        self.assertEqual(response.context["variant_rows"][0]["reserved_total"], Decimal("9.000"))
        self.assertContains(response, self.roll_reserved.identifier)
        self.assertContains(response, "TEC-STK-1")

    def test_stock_overview_reserved_filter_returns_only_partial_rolls(self):
        response = self.client.get(reverse("sales:stock_overview"), {"status": "reserved"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["rolls"]), 1)
        self.assertEqual(response.context["rolls"][0].pk, self.roll_reserved.pk)

    def test_stock_overview_color_scope_filters_rolls_panel(self):
        green = Color.objects.create(name="VERDE")
        self.product.colors.add(green)
        self.product.sync_variants()
        green_variant = self.product.variants.get(color=green)
        green_roll = FabricRoll.objects.create(
            stock_entry=self.entry,
            variant=green_variant,
            initial_quantity=Decimal("7.000"),
        )
        FabricRoll.refresh_many([green_roll.pk])

        response = self.client.get(
            reverse("sales:stock_overview"),
            {
                "product": self.product.reference,
                "color": str(green_variant.pk),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_product"]["reference"], self.product.reference)
        self.assertEqual(response.context["active_color"]["variant_id"], str(green_variant.pk))
        self.assertEqual(len(response.context["rolls"]), 1)
        self.assertEqual(response.context["rolls"][0].pk, green_roll.pk)
        self.assertContains(response, green_roll.identifier)

    def test_stock_movement_list_shows_generated_history(self):
        response = self.client.get(reverse("sales:stock_movement_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["movement_total"], 5)
        self.assertEqual(response.context["summary"]["roll_total"], 3)
        self.assertEqual(response.context["summary"]["entry_quantity"], Decimal("25.000"))
        self.assertEqual(response.context["summary"]["confirmed_quantity"], Decimal("9.000"))
        self.assertContains(response, self.roll_reserved.identifier)
        self.assertContains(response, "Confirmacao")

    def test_stock_movement_list_type_filter_returns_only_confirmed_rows(self):
        response = self.client.get(
            reverse("sales:stock_movement_list"),
            {"movement_type": StockMovementType.CONFIRMED},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["movements"]), 2)
        self.assertTrue(
            all(
                movement.movement_type == StockMovementType.CONFIRMED
                for movement in response.context["movements"]
            )
        )


class StockAdjustmentFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="ajuste_estoque",
            password="senha123456",
            full_name="Ajuste Estoque",
        )
        self.client.force_login(self.user)
        self.company = Company.objects.create(
            legal_name="CLIENTE AJUSTE LTDA",
            trade_name="Cliente Ajuste",
            cnpj="70.000.000/0001-70",
            city="Fortaleza",
            state="CE",
        )
        self.contact = Participant.objects.create(name="CONTATO AJUSTE")
        ParticipantCompany.objects.create(
            participant=self.contact,
            company=self.company,
            is_primary=True,
        )
        self.supplier = Supplier.objects.create(
            trade_name="FORNECEDOR AJUSTE",
            cnpj="71.000.000/0001-71",
            city="Fortaleza",
            state="CE",
        )
        self.category = Category.objects.create(name="AJUSTES")
        self.color = Color.objects.create(name="BEGE")
        self.product = Product.objects.create(
            category=self.category,
            reference="TEC-AJT-1",
            description="MALHA AJUSTE",
            price=Decimal("55.00"),
            unit=ProductUnit.METER,
            created_by=self.user,
        )
        self.product.colors.add(self.color)
        self.product.sync_variants()
        self.variant = self.product.variants.get()
        self.entry = StockEntry.objects.create(
            supplier=self.supplier,
            created_by=self.user,
        )
        self.roll = FabricRoll.objects.create(
            stock_entry=self.entry,
            variant=self.variant,
            initial_quantity=Decimal("10.000"),
        )

    def test_stock_adjustment_form_creates_manual_movement_and_updates_balance(self):
        order = Order.objects.create(
            buyer_company=self.company,
            participant=self.contact,
            status=OrderStatus.CONFIRMED,
            created_by=self.user,
        )
        OrderItem.objects.create(
            order=order,
            roll=self.roll,
            variant=self.variant,
            quantity=Decimal("4.000"),
            unit_price=Decimal("55.00"),
        )
        FabricRoll.refresh_many([self.roll.pk])

        response = self.client.post(
            reverse("sales:stock_adjustment_create", args=[self.roll.pk]),
            {
                "adjustment_type": StockAdjustmentType.ADJUSTMENT_OUT,
                "quantity": "1.500",
                "notes": "AVARIA",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.roll.refresh_from_db()
        self.assertEqual(self.roll.available_quantity, Decimal("4.500"))
        self.assertEqual(self.roll.adjustments.count(), 1)
        self.assertEqual(self.roll.adjustments.get().notes, "AVARIA")
        self.assertEqual(
            list(self.roll.movements.order_by("effective_at", "pk").values_list("movement_type", flat=True)),
            [
                StockMovementType.ENTRY,
                StockMovementType.CONFIRMED,
                StockMovementType.ADJUSTMENT_OUT,
            ],
        )

    def test_stock_adjustment_form_blocks_adjustment_out_above_available_balance(self):
        response = self.client.post(
            reverse("sales:stock_adjustment_create", args=[self.roll.pk]),
            {
                "adjustment_type": StockAdjustmentType.ADJUSTMENT_OUT,
                "quantity": "12.000",
                "notes": "PERDA",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "possui saldo disponivel de 10.000 MT")
        self.assertEqual(self.roll.adjustments.count(), 0)


class RollLookupViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="scanner",
            password="senha123456",
            full_name="Scanner Estoque",
        )
        self.client.force_login(self.user)
        self.supplier = Supplier.objects.create(
            trade_name="FORNECEDOR SCANNER",
            cnpj="80.000.000/0001-80",
            city="Fortaleza",
            state="CE",
        )
        self.category = Category.objects.create(name="SCANNER")
        self.color = Color.objects.create(name="VINHO")
        self.product = Product.objects.create(
            category=self.category,
            reference="TEC-SCAN-1",
            description="MALHA SCANNER",
            price=Decimal("32.50"),
            unit=ProductUnit.KILOGRAM,
            created_by=self.user,
        )
        self.product.colors.add(self.color)
        self.product.sync_variants()
        self.variant = self.product.variants.get()
        self.entry = StockEntry.objects.create(
            supplier=self.supplier,
            created_by=self.user,
        )
        self.roll = FabricRoll.objects.create(
            stock_entry=self.entry,
            variant=self.variant,
            initial_quantity=Decimal("8.750"),
        )

    def test_roll_lookup_accepts_qr_payload(self):
        response = self.client.get(
            reverse("sales:roll_lookup"),
            {"code": f"ROLO:{self.roll.identifier}"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["id"], self.roll.pk)
        self.assertEqual(payload["identifier"], self.roll.identifier)
        self.assertEqual(payload["available_quantity"], "8.750")
        self.assertEqual(payload["unit_price"], "32.50")


class OrderWholeRollFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="pedido_rolo_fechado",
            password="senha123456",
            full_name="Pedido Rolo Fechado",
        )
        self.client.force_login(self.user)
        self.company = Company.objects.create(
            legal_name="CLIENTE ROLO LTDA",
            trade_name="Cliente Rolo",
            cnpj="81.000.000/0001-81",
            city="Fortaleza",
            state="CE",
        )
        self.contact = Participant.objects.create(name="CONTATO ROLO")
        ParticipantCompany.objects.create(
            participant=self.contact,
            company=self.company,
            is_primary=True,
        )
        self.supplier = Supplier.objects.create(
            trade_name="FORNECEDOR PEDIDO",
            cnpj="82.000.000/0001-82",
            city="Fortaleza",
            state="CE",
        )
        self.category = Category.objects.create(name="PEDIDOS FECHADOS")
        self.color = Color.objects.create(name="CARAMELO")
        self.product = Product.objects.create(
            category=self.category,
            reference="TEC-FECH-1",
            description="MALHA FECHADA",
            price=Decimal("32.50"),
            unit=ProductUnit.KILOGRAM,
            created_by=self.user,
        )
        self.product.colors.add(self.color)
        self.product.sync_variants()
        self.variant = self.product.variants.get()
        self.entry = StockEntry.objects.create(
            supplier=self.supplier,
            created_by=self.user,
        )
        self.roll = FabricRoll.objects.create(
            stock_entry=self.entry,
            variant=self.variant,
            initial_quantity=Decimal("8.750"),
        )

    def test_order_create_forces_full_roll_quantity_and_fixed_unit_price(self):
        response = self.client.post(
            reverse("sales:order_create"),
            {
                "buyer_company": str(self.company.pk),
                "participant": str(self.contact.pk),
                "representative": "",
                "status": OrderStatus.CONFIRMED,
                "delivery_deadline": "",
                "freight_type": "FOB",
                "carrier": "",
                "payment_method": "",
                "payment_terms": "",
                "discount_type": "P",
                "discount_value": "0",
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-id": "",
                "items-0-roll": str(self.roll.pk),
                "items-0-quantity": "1.000",
                "items-0-unit_price": "999.99",
                "items-0-notes": "Teste",
            },
        )

        self.assertEqual(response.status_code, 302)
        order = Order.objects.latest("pk")
        item = order.items.get()
        self.roll.refresh_from_db()

        self.assertEqual(item.quantity, Decimal("8.750"))
        self.assertEqual(item.unit_price, Decimal("32.50"))
        self.assertEqual(order.subtotal_amount, Decimal("284.38"))
        self.assertEqual(self.roll.available_quantity, Decimal("0.000"))


class OrderFormDisplayTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="pedido_display",
            password="senha123456",
            full_name="Pedido Display",
        )
        self.client.force_login(self.user)

    def test_order_form_extra_rows_do_not_prefill_invalid_zero_quantities(self):
        response = self.client.get(reverse("sales:order_create"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'value="0.000"')

    def test_order_form_uses_dynamic_template_for_scanned_rows(self):
        response = self.client.get(reverse("sales:order_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-empty-form-template")
        self.assertContains(response, "Cada leitura cria uma nova linha automaticamente.")
