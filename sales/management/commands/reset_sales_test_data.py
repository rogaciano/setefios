from django.core.management.base import BaseCommand
from django.db import transaction

from sales.models import FabricRoll, Order, OrderItem, StockAdjustment, StockEntry, StockMovement


def _counts():
    return {
        "orders": Order.objects.count(),
        "order_items": OrderItem.objects.count(),
        "entries": StockEntry.objects.count(),
        "rolls": FabricRoll.objects.count(),
        "adjustments": StockAdjustment.objects.count(),
        "movements": StockMovement.objects.count(),
    }


class Command(BaseCommand):
    help = "Remove pedidos e entradas de estoque usados em testes locais."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Executa a limpeza imediatamente.",
        )

    def handle(self, *args, **options):
        before = _counts()

        if not options["force"]:
            self.stdout.write(self.style.WARNING("Use --force para confirmar a limpeza de pedidos e entradas."))
            self.stdout.write(f"Estado atual: {before}")
            return

        order_ids = list(Order.objects.values_list("pk", flat=True))
        entry_ids = list(StockEntry.objects.values_list("pk", flat=True))

        with transaction.atomic():
            Order.objects.filter(pk__in=order_ids).delete()
            StockEntry.objects.filter(pk__in=entry_ids).delete()

        after = _counts()
        self.stdout.write(self.style.SUCCESS("Limpeza concluida."))
        self.stdout.write(f"Antes: {before}")
        self.stdout.write(f"Depois: {after}")
        self.stdout.write(f"Pedidos removidos: {order_ids}")
        self.stdout.write(f"Entradas removidas: {entry_ids}")
