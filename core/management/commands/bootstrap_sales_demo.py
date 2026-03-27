from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from core.models import Company, Participant, ParticipantCompany, Supplier
from sales.models import Category, Color, FabricRoll, Order, OrderItem, Product, ProductUnit, StockEntry


class Command(BaseCommand):
    help = "Cria uma base inicial para testar o sistema de vendas em Django."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument("--password", default="admin123456")

    def _fill_variant_barcodes(self, product, seed):
        for index, variant in enumerate(
            product.variants.select_related("color").order_by("color__name"),
            start=1,
        ):
            barcode = f"{seed}{index:04d}"
            if variant.barcode != barcode:
                variant.barcode = barcode
                variant.save(update_fields=["barcode", "updated_at"])

    @transaction.atomic
    def handle(self, *args, **options):
        client_main, _ = Company.objects.get_or_create(
            cnpj="11.111.111/0001-11",
            defaults={
                "legal_name": "LOJA MODELO LTDA",
                "trade_name": "Loja Modelo",
                "city": "Juazeiro do Norte",
                "state": "CE",
                "email": "compras@lojamodelo.local",
                "phone": "(88) 99999-0000",
            },
        )
        client_secondary, _ = Company.objects.get_or_create(
            cnpj="22.222.222/0001-22",
            defaults={
                "legal_name": "BOUTIQUE CENTRO SUL LTDA",
                "trade_name": "Boutique Centro Sul",
                "city": "Fortaleza",
                "state": "CE",
                "email": "compras@centrosul.local",
            },
        )
        supplier, _ = Supplier.objects.get_or_create(
            cnpj="33.333.333/0001-33",
            defaults={
                "trade_name": "TECELAGEM MODELO",
                "contact_name": "CARLA FORNECEDORA",
                "phone": "(85) 98888-1111",
                "email": "contato@tecelagemmodelo.local",
                "city": "Fortaleza",
                "state": "CE",
            },
        )

        buyer_contact, _ = Participant.objects.get_or_create(
            name="MARIA COMPRADORA",
            defaults={
                "email": "maria@lojamodelo.local",
                "phone": "(88) 98888-0000",
            },
        )
        buyer_contact_secondary, _ = Participant.objects.get_or_create(
            name="ANA GESTORA",
            defaults={
                "email": "ana@centrosul.local",
                "phone": "(85) 97777-0000",
            },
        )
        rep, _ = Participant.objects.get_or_create(
            name="JOAO REPRESENTANTE",
            defaults={
                "email": "joao@setefios.local",
                "is_representative": True,
                "commission_percentage": 7.5,
            },
        )
        rep.is_representative = True
        rep.commission_percentage = rep.commission_percentage or 7.5
        rep.save(update_fields=["is_representative", "commission_percentage"])

        ParticipantCompany.objects.get_or_create(
            participant=buyer_contact,
            company=client_main,
            defaults={"is_primary": True},
        )
        ParticipantCompany.objects.get_or_create(
            participant=buyer_contact_secondary,
            company=client_secondary,
            defaults={"is_primary": True},
        )

        user, _ = User.objects.get_or_create(
            username=options["username"],
            defaults={
                "full_name": "Administrador do Sistema",
                "email": "admin@setefios.local",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        user.full_name = user.full_name or "Administrador do Sistema"
        user.email = user.email or "admin@setefios.local"
        user.is_staff = True
        user.is_superuser = True
        user.set_password(options["password"])
        user.save()

        woven_category, _ = Category.objects.get_or_create(name="TECIDOS PLANOS")
        knit_category, _ = Category.objects.get_or_create(name="MALHAS")
        colors = [
            Color.objects.get_or_create(name=name)[0]
            for name in ("PRETO", "OFF WHITE", "AZUL PETROLEO")
        ]

        product, _ = Product.objects.get_or_create(
            reference="TEC-001",
            defaults={
                "category": woven_category,
                "description": "VISCOLINHO PREMIUM",
                "price": Decimal("79.90"),
                "unit": ProductUnit.METER,
                "created_by": user,
            },
        )
        product.category = woven_category
        product.description = "VISCOLINHO PREMIUM"
        product.price = Decimal("79.90")
        product.unit = ProductUnit.METER
        if not product.created_by_id:
            product.created_by = user
        product.save()
        product.colors.set(colors)
        product.sync_variants()
        self._fill_variant_barcodes(product, "789100")

        product_secondary, _ = Product.objects.get_or_create(
            reference="TEC-002",
            defaults={
                "category": knit_category,
                "description": "MALHA CANELADA",
                "price": Decimal("129.90"),
                "unit": ProductUnit.KILOGRAM,
                "created_by": user,
            },
        )
        product_secondary.category = knit_category
        product_secondary.description = "MALHA CANELADA"
        product_secondary.price = Decimal("129.90")
        product_secondary.unit = ProductUnit.KILOGRAM
        if not product_secondary.created_by_id:
            product_secondary.created_by = user
        product_secondary.save()
        product_secondary.colors.set(colors[:2])
        product_secondary.sync_variants()
        self._fill_variant_barcodes(product_secondary, "789200")

        stock_entry = StockEntry.objects.filter(
            supplier=supplier,
            notes="Entrada demo para rolos de tecido.",
        ).order_by("pk").first()
        if stock_entry is None:
            stock_entry = StockEntry.objects.create(
                supplier=supplier,
                received_at="2026-03-25",
                notes="Entrada demo para rolos de tecido.",
                created_by=user,
            )

        demo_rolls = [
            (product.variants.order_by("pk").first(), Decimal("32.500")),
            (product.variants.order_by("pk")[1] if product.variants.count() > 1 else None, Decimal("28.750")),
            (product_secondary.variants.order_by("pk").first(), Decimal("18.200")),
        ]
        created_roll_ids = []
        for variant, quantity in demo_rolls:
            if not variant:
                continue
            roll = stock_entry.rolls.filter(variant=variant, initial_quantity=quantity).order_by("pk").first()
            if roll is None:
                roll = FabricRoll.objects.create(
                    stock_entry=stock_entry,
                    variant=variant,
                    initial_quantity=quantity,
                    notes="Rolo demo",
                )
            created_roll_ids.append(roll.pk)

        demo_roll = stock_entry.rolls.select_related("variant__product", "variant__color").filter(
            variant__product=product,
            variant__is_active=True,
        ).order_by("pk").first()
        if demo_roll:
            order = Order.objects.filter(
                buyer_company=client_main,
                participant=buyer_contact,
                notes="Pedido demo da nova stack.",
            ).order_by("pk").first()

            if order is None:
                order = Order.objects.create(
                    buyer_company=client_main,
                    participant=buyer_contact,
                    representative=rep,
                    status="confirmed",
                    delivery_deadline="15 DIAS",
                    payment_method="BOLETO",
                    payment_terms="30/60",
                    carrier="TRANSPORTADORA MODELO",
                    notes="Pedido demo da nova stack.",
                    created_by=user,
                )
            else:
                order.representative = rep
                order.status = "confirmed"
                order.delivery_deadline = "15 DIAS"
                order.payment_method = "BOLETO"
                order.payment_terms = "30/60"
                order.carrier = "TRANSPORTADORA MODELO"
                order.updated_by = user
                order.save()

            item = order.items.order_by("pk").first()
            if item is None:
                item = OrderItem(order=order)
            item.roll = demo_roll
            item.variant = demo_roll.variant
            item.quantity = Decimal("12.500")
            item.unit_price = demo_roll.variant.product.price
            item.notes = "Separado do rolo demo"
            item.save()
            order.items.exclude(pk=item.pk).delete()
            order.recalculate_totals()
            FabricRoll.refresh_many([demo_roll.pk])

        FabricRoll.refresh_many(created_roll_ids)

        self.stdout.write(self.style.SUCCESS("Base inicial criada com sucesso."))
        self.stdout.write(
            self.style.WARNING(
                f"Login: {options['username']} | Senha: {options['password']}"
            )
        )


