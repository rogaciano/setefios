from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sales.models import Category, Color, FabricRoll, OrderItem, Product, ProductVariant


def _counts():
    return {
        "products": Product.objects.count(),
        "variants": ProductVariant.objects.count(),
        "categories": Category.objects.count(),
        "colors": Color.objects.count(),
        "roll_links": FabricRoll.objects.count(),
        "order_item_links": OrderItem.objects.count(),
    }


class Command(BaseCommand):
    help = "Remove produtos, variantes e cadastros auxiliares orfaos usados em testes locais."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Executa a limpeza imediatamente.",
        )

    def handle(self, *args, **options):
        before = _counts()

        if not options["force"]:
            self.stdout.write(self.style.WARNING("Use --force para confirmar a limpeza de produtos e grade."))
            self.stdout.write(f"Estado atual: {before}")
            return

        if before["roll_links"] or before["order_item_links"]:
            raise CommandError(
                "Ainda existem rolos ou itens de pedido ligados ao catalogo. Rode primeiro 'python manage.py reset_sales_test_data --force'."
            )

        product_ids = list(Product.objects.values_list("pk", flat=True))

        with transaction.atomic():
            Product.objects.filter(pk__in=product_ids).delete()
            Category.objects.filter(products__isnull=True).delete()
            Color.objects.filter(products__isnull=True, variants__isnull=True).delete()

        after = _counts()
        self.stdout.write(self.style.SUCCESS("Limpeza do catalogo concluida."))
        self.stdout.write(f"Antes: {before}")
        self.stdout.write(f"Depois: {after}")
        self.stdout.write(f"Produtos removidos: {product_ids}")
