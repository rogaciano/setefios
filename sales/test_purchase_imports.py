from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from accounts.models import User

from .models import Category, Product, ProductUnit
from .purchase_imports import PurchaseDocumentAnalyzer


class PurchaseDocumentAnalyzerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.docs_dir = Path(settings.BASE_DIR) / "docs"
        cls.user = User.objects.create_user(
            username="importador_docs",
            password="senha123456",
            full_name="Importador Docs",
        )
        cls.category = Category.objects.create(name="IMPORTADOS")
        Product.objects.create(
            category=cls.category,
            reference="0010121",
            description="MADRI PROTECAO UV",
            price=Decimal("10.00"),
            unit=ProductUnit.KILOGRAM,
            created_by=cls.user,
        )
        Product.objects.create(
            category=cls.category,
            reference="00139000000-000",
            description="POLISIDE LISO 170 GR 1,70 LARG",
            price=Decimal("10.00"),
            unit=ProductUnit.KILOGRAM,
            created_by=cls.user,
        )

    def setUp(self):
        self.analyzer = PurchaseDocumentAnalyzer()

    def test_parse_basic_faturamento_xlsx(self):
        result = self.analyzer.analyze_file(self.docs_dir / "008131.xlsx")
        document = result.document

        self.assertEqual(document.parser_key, "faturamento_xlsx_basic")
        self.assertEqual(document.note_number, "008131")
        self.assertEqual(document.supplier_hint, "THAMI TEX MALHAS LTDA")
        self.assertEqual(len(document.products), 1)
        self.assertEqual(result.matched_total, 1)

        product = document.products[0]
        self.assertEqual(product.reference, "0010121")
        self.assertEqual(product.unit, ProductUnit.KILOGRAM)
        self.assertGreaterEqual(len(product.colors), 3)

        amarelo = next(color for color in product.colors if color.code == "0010")
        verde = next(color for color in product.colors if color.code == "0026")
        self.assertEqual(amarelo.total_quantity, Decimal("261.660"))
        self.assertEqual(verde.total_quantity, Decimal("536.140"))
        self.assertEqual(amarelo.rolls[0].external_code, "")

    def test_parse_lote_faturamento_xlsx(self):
        result = self.analyzer.analyze_file(self.docs_dir / "DANIEL - 921316.xlsx")
        document = result.document

        self.assertEqual(document.parser_key, "faturamento_xlsx_lote")
        self.assertEqual(document.note_number, "921316")
        self.assertIn("LIATHU", document.supplier_hint)
        self.assertTrue(document.supplier_hint.startswith("DEMONSTRA"))
        self.assertEqual(len(document.products), 1)
        self.assertEqual(result.matched_total, 1)

        product = document.products[0]
        self.assertEqual(product.reference, "00139000000-000")
        self.assertEqual(product.total_quantity, Decimal("719.810"))

        verde = next(color for color in product.colors if color.code == "4050")
        self.assertEqual(verde.rolls[0].external_code, "014066228")
        self.assertEqual(verde.rolls[0].quantity, Decimal("17.650"))

    def test_parse_nfe_xml_document(self):
        result = self.analyzer.analyze_file(self.docs_dir / "DAMENNYxml (1).xml")
        document = result.document

        self.assertEqual(document.parser_key, "nfe_xml")
        self.assertEqual(document.supplier_hint, "DAMENNY IND COM DE PRO TEXTEIS LTDA")
        self.assertTrue(document.note_number)
        self.assertEqual(len(document.products), 1)
        self.assertEqual(result.matched_total, 0)
        self.assertTrue(document.warnings)

        product = document.products[0]
        self.assertEqual(product.reference, "1.CE999.999.000057")
        self.assertEqual(product.unit, ProductUnit.METER)
        self.assertEqual(product.total_quantity, Decimal("21.000"))

    def test_analyze_directory_keeps_invalid_files_visible(self):
        results = self.analyzer.analyze_directory(self.docs_dir)
        by_name = {result.document.source_name: result for result in results}

        self.assertIn("DAMENNYxml.xml", by_name)
        self.assertEqual(by_name["DAMENNYxml.xml"].document.parser_key, "error")
        self.assertIn("vazio", by_name["DAMENNYxml.xml"].document.warnings[0].lower())

        self.assertIn("DAMENNY.pdf", by_name)
        self.assertEqual(by_name["DAMENNY.pdf"].document.parser_key, "pdf_pending")
        self.assertTrue(by_name["DAMENNY.pdf"].document.warnings)
