from pathlib import Path

from django.core.management.base import BaseCommand

from sales.purchase_imports import PurchaseDocumentAnalyzer, PurchaseImportError


class Command(BaseCommand):
    help = "Diagnostica documentos de compra e cruza as referencias com o cadastro de produtos."

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            nargs="?",
            default="docs",
            help="Arquivo ou pasta com documentos para diagnostico.",
        )

    def handle(self, *args, **options):
        analyzer = PurchaseDocumentAnalyzer()
        base_path = Path(options["path"])

        try:
            results = analyzer.analyze_directory(base_path)
        except PurchaseImportError as exc:
            raise SystemExit(str(exc))

        if not results:
            self.stdout.write("Nenhum documento suportado encontrado.")
            return

        for result in results:
            document = result.document
            product_total = len(document.products)
            color_total = sum(len([color for color in product.colors if color.name]) for product in document.products)
            roll_total = sum(len(color.rolls) for product in document.products for color in product.colors)

            self.stdout.write("")
            self.stdout.write(f"{document.source_name} [{document.parser_key}]")
            if document.supplier_hint:
                self.stdout.write(f"  fornecedor sugerido: {document.supplier_hint}")
            if document.note_number:
                self.stdout.write(f"  nota: {document.note_number}")
            self.stdout.write(
                f"  produtos: {product_total} | cores: {color_total} | rolos: {roll_total} | encontrados: {result.matched_total}/{len(result.diagnoses)}"
            )

            for warning in document.warnings:
                self.stdout.write(f"  aviso: {warning}")

            preview = result.diagnoses[:8]
            for diagnosis in preview:
                status = "ok" if diagnosis.exists else "novo"
                self.stdout.write(
                    f"  - [{status}] {diagnosis.reference} | {diagnosis.description} | cores {diagnosis.color_total} | rolos {diagnosis.roll_total}"
                )

            extra_total = len(result.diagnoses) - len(preview)
            if extra_total > 0:
                self.stdout.write(f"  ... {extra_total} item(ns) a mais")
