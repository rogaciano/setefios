from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class NamedModel(models.Model):
    name = models.CharField(max_length=120, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ("name",)

    def save(self, *args, **kwargs):
        self.name = (self.name or "").strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Category(NamedModel):
    class Meta(NamedModel.Meta):
        verbose_name = "categoria"
        verbose_name_plural = "categorias"


class Color(NamedModel):
    class Meta(NamedModel.Meta):
        verbose_name = "cor"
        verbose_name_plural = "cores"


class ProductUnit(models.TextChoices):
    METER = "MT", "Metro"
    KILOGRAM = "KG", "Peso (kg)"


class StockMovementType(models.TextChoices):
    ENTRY = "entry", "Entrada"
    ADJUSTMENT_IN = "adjustment_in", "Ajuste de entrada"
    ADJUSTMENT_OUT = "adjustment_out", "Ajuste de saida"
    RETURN = "return", "Devolucao"
    RESERVED = "reserved", "Reserva"
    CONFIRMED = "confirmed", "Confirmacao"


class StockAdjustmentType(models.TextChoices):
    ADJUSTMENT_IN = "adjustment_in", "Ajuste de entrada"
    ADJUSTMENT_OUT = "adjustment_out", "Ajuste de saida"
    RETURN = "return", "Devolucao"

    @classmethod
    def positive_values(cls):
        return [cls.ADJUSTMENT_IN, cls.RETURN]


class OrderStatus(models.TextChoices):
    DRAFT = "draft", "Rascunho"
    RESERVED = "reserved", "Reservado"
    CONFIRMED = "confirmed", "Confirmado"
    CANCELLED = "cancelled", "Cancelado"

    @classmethod
    def reserving_values(cls):
        return [cls.RESERVED, cls.CONFIRMED]


class DiscountType(models.TextChoices):
    PERCENTAGE = "P", "Percentual"
    AMOUNT = "A", "Valor fixo"


class FreightType(models.TextChoices):
    CIF = "CIF", "Pago (CIF)"
    FOB = "FOB", "A pagar (FOB)"


class Product(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="categoria",
    )
    reference = models.CharField("referencia", max_length=20, unique=True)
    description = models.CharField("descricao", max_length=255)
    price = models.DecimalField(
        "preco",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    unit = models.CharField(
        "unidade",
        max_length=2,
        choices=ProductUnit.choices,
        default=ProductUnit.METER,
    )
    colors = models.ManyToManyField(
        Color,
        related_name="products",
        blank=True,
        verbose_name="cores",
    )
    is_active = models.BooleanField("ativo", default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="products_created",
        verbose_name="criado por",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="products_updated",
        null=True,
        blank=True,
        verbose_name="atualizado por",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "produto"
        verbose_name_plural = "produtos"
        ordering = ("description",)

    def save(self, *args, **kwargs):
        self.reference = (self.reference or "").strip().upper()
        self.description = (self.description or "").strip().upper()
        super().save(*args, **kwargs)

    def sync_variants(self):
        selected_colors = set(self.colors.values_list("pk", flat=True))
        existing_variants = {
            variant.color_id: variant
            for variant in self.variants.select_related("color")
        }

        for color_id in selected_colors:
            variant = existing_variants.get(color_id)
            if variant:
                if not variant.is_active:
                    variant.is_active = True
                    variant.save(update_fields=["is_active"])
                continue

            ProductVariant.objects.create(
                product=self,
                color_id=color_id,
                is_active=True,
            )

        for color_id, variant in existing_variants.items():
            if color_id in selected_colors:
                continue
            if variant.order_items.exists() or variant.rolls.exists():
                if variant.is_active:
                    variant.is_active = False
                    variant.save(update_fields=["is_active"])
            else:
                variant.delete()

    def __str__(self):
        return f"{self.reference} - {self.description}"


class ProductVariant(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="variants",
    )
    color = models.ForeignKey(Color, on_delete=models.PROTECT, related_name="variants")
    barcode = models.CharField("codigo de barras", max_length=64, blank=True)
    is_active = models.BooleanField("ativo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "variante do produto"
        verbose_name_plural = "variantes do produto"
        ordering = ("product__reference", "color__name")
        constraints = [
            models.UniqueConstraint(
                fields=("product", "color"),
                name="unique_variant_by_color",
            )
        ]

    def save(self, *args, **kwargs):
        self.barcode = (self.barcode or "").strip()
        super().save(*args, **kwargs)

    @property
    def label(self):
        return (
            f"{self.product.reference} | {self.product.description} | "
            f"{self.color.name} | {self.product.get_unit_display()}"
        )

    def __str__(self):
        return self.label


class StockEntry(models.Model):
    supplier = models.ForeignKey(
        "core.Supplier",
        on_delete=models.PROTECT,
        related_name="stock_entries",
        verbose_name="fornecedor",
    )
    received_at = models.DateField("data de entrada", default=timezone.localdate)
    notes = models.TextField("observacoes", blank=True)
    source_note_number = models.CharField("nota de origem", max_length=40, blank=True, default="", db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="stock_entries_created",
        verbose_name="criado por",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "entrada de estoque"
        verbose_name_plural = "entradas de estoque"
        ordering = ("-received_at", "-pk")

    def save(self, *args, **kwargs):
        self.notes = (self.notes or "").strip()
        self.source_note_number = (self.source_note_number or "").strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Entrada #{self.pk}"


class FabricRoll(models.Model):
    stock_entry = models.ForeignKey(
        StockEntry,
        on_delete=models.CASCADE,
        related_name="rolls",
        verbose_name="entrada",
    )
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.PROTECT,
        related_name="rolls",
        verbose_name="variante",
    )
    identifier = models.CharField("codigo do rolo", max_length=24, unique=True, blank=True)
    initial_quantity = models.DecimalField(
        "quantidade inicial",
        max_digits=10,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    available_quantity = models.DecimalField(
        "saldo disponivel",
        max_digits=10,
        decimal_places=3,
        default=0,
        validators=[MinValueValidator(Decimal("0.000"))],
    )
    notes = models.CharField("observacoes", max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "rolo de tecido"
        verbose_name_plural = "rolos de tecido"
        ordering = ("-created_at", "-pk")

    def save(self, *args, **kwargs):
        self.notes = (self.notes or "").strip()
        is_new = self._state.adding
        if is_new and (self.available_quantity is None or self.available_quantity == Decimal("0.000")):
            self.available_quantity = self.initial_quantity or Decimal("0.000")

        super().save(*args, **kwargs)

        if is_new and not self.identifier:
            self.identifier = f"ROL{self.pk:08d}"
            super().save(update_fields=["identifier", "updated_at"])

    def reserved_quantity(self, exclude_order=None):
        reservations = self.order_items.filter(order__status__in=OrderStatus.reserving_values())
        if exclude_order is not None:
            reservations = reservations.exclude(order=exclude_order)
        total = reservations.aggregate(total=Sum("quantity"))["total"] or Decimal("0.000")
        return total.quantize(Decimal("0.001"))

    def adjustment_delta(self, exclude_adjustment=None):
        total = Decimal("0.000")
        adjustments = self.adjustments.all()
        if exclude_adjustment is not None:
            adjustments = adjustments.exclude(pk=exclude_adjustment.pk)
        for adjustment in adjustments:
            total += adjustment.signed_quantity
        return total.quantize(Decimal("0.001"))

    def physical_quantity(self, exclude_adjustment=None):
        total = (self.initial_quantity or Decimal("0.000")) + self.adjustment_delta(exclude_adjustment=exclude_adjustment)
        if total < 0:
            total = Decimal("0.000")
        return total.quantize(Decimal("0.001"))

    def sellable_quantity(self, exclude_order=None, exclude_adjustment=None):
        available = self.physical_quantity(exclude_adjustment=exclude_adjustment) - self.reserved_quantity(exclude_order=exclude_order)
        if available < 0:
            available = Decimal("0.000")
        return available.quantize(Decimal("0.001"))

    def refresh_availability(self):
        self.available_quantity = self.sellable_quantity()
        self.save(update_fields=["available_quantity", "updated_at"])
        StockMovement.sync_for_roll(self)

    @classmethod
    def refresh_many(cls, roll_ids):
        for roll in cls.objects.filter(pk__in=[roll_id for roll_id in roll_ids if roll_id]):
            roll.refresh_availability()

    @property
    def qr_payload(self):
        return f"ROLO:{self.identifier or self.pk}"

    @property
    def barcode_value(self):
        return self.identifier or f"ROL{self.pk:08d}"

    @property
    def unit_code(self):
        return self.variant.product.unit

    @property
    def unit_display(self):
        return self.variant.product.get_unit_display()

    @property
    def label(self):
        return f"{self.identifier} | {self.variant.label}"

    def __str__(self):
        return self.label


class Order(models.Model):
    buyer_company = models.ForeignKey(
        "core.Company",
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="cliente",
    )
    participant = models.ForeignKey(
        "core.Participant",
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="comprador",
    )
    representative = models.ForeignKey(
        "core.Participant",
        on_delete=models.PROTECT,
        related_name="represented_orders",
        null=True,
        blank=True,
        verbose_name="representante",
    )
    status = models.CharField(
        "status",
        max_length=16,
        choices=OrderStatus.choices,
        default=OrderStatus.DRAFT,
    )
    delivery_deadline = models.CharField("prazo de entrega", max_length=120, blank=True)
    payment_method = models.CharField("forma de pagamento", max_length=120, blank=True)
    payment_terms = models.CharField("condicao de pagamento", max_length=120, blank=True)
    carrier = models.CharField("transportadora", max_length=120, blank=True)
    freight_type = models.CharField(
        "frete",
        max_length=3,
        choices=FreightType.choices,
        default=FreightType.FOB,
    )
    notes = models.TextField("observacoes", blank=True)
    discount_type = models.CharField(
        "tipo de desconto",
        max_length=1,
        choices=DiscountType.choices,
        default=DiscountType.PERCENTAGE,
    )
    discount_value = models.DecimalField(
        "desconto",
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    subtotal_amount = models.DecimalField(
        "subtotal",
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    total_amount = models.DecimalField(
        "total",
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    total_pieces = models.PositiveIntegerField("itens", default=0)
    webpic_integrated = models.BooleanField("integrado na Webpic", default=False)
    webpic_payload = models.JSONField("payload Webpic", null=True, blank=True)
    webpic_response = models.JSONField("resposta Webpic", null=True, blank=True)
    webpic_exported_at = models.DateTimeField("exportado em", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders_created",
        verbose_name="criado por",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders_updated",
        null=True,
        blank=True,
        verbose_name="atualizado por",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "pedido"
        verbose_name_plural = "pedidos"
        ordering = ("-created_at",)

    def save(self, *args, **kwargs):
        upper_fields = (
            "delivery_deadline",
            "payment_method",
            "payment_terms",
            "carrier",
        )
        for field in upper_fields:
            value = getattr(self, field, "")
            setattr(self, field, (value or "").strip().upper())
        self.notes = (self.notes or "").strip()
        super().save(*args, **kwargs)

    def recalculate_totals(self):
        subtotal = Decimal("0.00")
        line_count = 0

        for item in self.items.select_related("variant__product"):
            subtotal += item.line_total
            if item.quantity:
                line_count += 1

        discount = self.discount_value or Decimal("0.00")
        if self.discount_type == DiscountType.PERCENTAGE:
            total = subtotal * (Decimal("1.00") - (discount / Decimal("100.00")))
        else:
            total = subtotal - discount

        if total < 0:
            total = Decimal("0.00")

        self.subtotal_amount = subtotal.quantize(Decimal("0.01"))
        self.total_amount = total.quantize(Decimal("0.01"))
        self.total_pieces = line_count
        self.save(
            update_fields=[
                "subtotal_amount",
                "total_amount",
                "total_pieces",
                "updated_at",
            ]
        )

    def __str__(self):
        return f"Pedido #{self.pk}"


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.PROTECT,
        related_name="order_items",
        verbose_name="variante",
    )
    roll = models.ForeignKey(
        FabricRoll,
        on_delete=models.PROTECT,
        related_name="order_items",
        verbose_name="rolo",
        null=True,
        blank=True,
    )
    quantity = models.DecimalField(
        "quantidade",
        max_digits=10,
        decimal_places=3,
        default=Decimal("0.000"),
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    unit_price = models.DecimalField(
        "valor unitario",
        max_digits=10,
        decimal_places=2,
        default=0,
    )
    notes = models.CharField("observacoes", max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "item do pedido"
        verbose_name_plural = "itens do pedido"
        ordering = ("pk",)

    def save(self, *args, **kwargs):
        if self.roll_id:
            self.variant = self.roll.variant
        if self.variant_id and not self.unit_price:
            self.unit_price = self.variant.product.price
        self.notes = (self.notes or "").strip()
        super().save(*args, **kwargs)

    @property
    def source_variant(self):
        if self.roll_id:
            return self.roll.variant
        return self.variant

    @property
    def line_total(self):
        return (self.unit_price or Decimal("0.00")) * (self.quantity or Decimal("0.000"))

    def __str__(self):
        return f"{self.source_variant} x {self.quantity}"


class StockAdjustment(models.Model):
    roll = models.ForeignKey(
        FabricRoll,
        on_delete=models.CASCADE,
        related_name="adjustments",
        verbose_name="rolo",
    )
    adjustment_type = models.CharField(
        "tipo",
        max_length=16,
        choices=StockAdjustmentType.choices,
    )
    quantity = models.DecimalField(
        "quantidade",
        max_digits=10,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    notes = models.CharField("observacoes", max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="stock_adjustments_created",
        verbose_name="criado por",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "ajuste de estoque"
        verbose_name_plural = "ajustes de estoque"
        ordering = ("-created_at", "-pk")

    @property
    def signed_quantity(self):
        quantity = self.quantity or Decimal("0.000")
        if self.adjustment_type in StockAdjustmentType.positive_values():
            return quantity
        return quantity * Decimal("-1")

    @property
    def movement_type(self):
        if self.adjustment_type == StockAdjustmentType.ADJUSTMENT_IN:
            return StockMovementType.ADJUSTMENT_IN
        if self.adjustment_type == StockAdjustmentType.ADJUSTMENT_OUT:
            return StockMovementType.ADJUSTMENT_OUT
        return StockMovementType.RETURN

    def save(self, *args, **kwargs):
        self.notes = (self.notes or "").strip()
        super().save(*args, **kwargs)
        roll = FabricRoll.objects.filter(pk=self.roll_id).first()
        if roll:
            roll.refresh_availability()

    def delete(self, *args, **kwargs):
        roll_id = self.roll_id
        super().delete(*args, **kwargs)
        roll = FabricRoll.objects.filter(pk=roll_id).first()
        if roll:
            roll.refresh_availability()

    def __str__(self):
        return f"{self.get_adjustment_type_display()} | {self.roll.identifier} | {self.quantity}"


class StockMovement(models.Model):
    roll = models.ForeignKey(
        FabricRoll,
        on_delete=models.CASCADE,
        related_name="movements",
        verbose_name="rolo",
    )
    movement_type = models.CharField(
        "tipo",
        max_length=16,
        choices=StockMovementType.choices,
    )
    quantity = models.DecimalField(
        "quantidade",
        max_digits=10,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    balance_after = models.DecimalField(
        "saldo apos movimentacao",
        max_digits=10,
        decimal_places=3,
        default=0,
        validators=[MinValueValidator(Decimal("0.000"))],
    )
    stock_entry = models.ForeignKey(
        StockEntry,
        on_delete=models.SET_NULL,
        related_name="stock_movements",
        verbose_name="entrada",
        null=True,
        blank=True,
    )
    stock_adjustment = models.ForeignKey(
        StockAdjustment,
        on_delete=models.SET_NULL,
        related_name="stock_movements",
        verbose_name="ajuste",
        null=True,
        blank=True,
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        related_name="stock_movements",
        verbose_name="pedido",
        null=True,
        blank=True,
    )
    order_item = models.ForeignKey(
        OrderItem,
        on_delete=models.SET_NULL,
        related_name="stock_movements",
        verbose_name="item do pedido",
        null=True,
        blank=True,
    )
    is_system_generated = models.BooleanField("gerado pelo sistema", default=True)
    effective_at = models.DateTimeField("data da movimentacao")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "movimentacao de estoque"
        verbose_name_plural = "movimentacoes de estoque"
        ordering = ("-effective_at", "-pk")

    @classmethod
    def positive_values(cls):
        return [
            StockMovementType.ENTRY,
            StockMovementType.ADJUSTMENT_IN,
            StockMovementType.RETURN,
        ]

    @property
    def signed_quantity(self):
        quantity = self.quantity or Decimal("0.000")
        if self.movement_type in self.positive_values():
            return quantity
        return quantity * Decimal("-1")

    @property
    def direction(self):
        if self.movement_type in self.positive_values():
            return "in"
        return "out"

    @property
    def source_label(self):
        if self.movement_type == StockMovementType.ENTRY and self.stock_entry_id:
            return f"Entrada #{self.stock_entry_id}"
        if self.stock_adjustment_id:
            return f"{self.stock_adjustment.get_adjustment_type_display()} #{self.stock_adjustment_id}"
        if self.order_id:
            return f"Pedido #{self.order_id}"
        return "-"

    @classmethod
    def sync_for_roll(cls, roll):
        cls.objects.filter(roll=roll, is_system_generated=True).delete()

        balance = (roll.initial_quantity or Decimal("0.000")).quantize(Decimal("0.001"))
        movements = [
            cls(
                roll=roll,
                movement_type=StockMovementType.ENTRY,
                quantity=balance,
                balance_after=balance,
                stock_entry=roll.stock_entry,
                effective_at=roll.created_at,
            )
        ]

        events = []
        for adjustment in roll.adjustments.all().order_by("created_at", "pk"):
            events.append((adjustment.created_at, 1, adjustment.pk, "adjustment", adjustment))

        order_items = roll.order_items.filter(
            order__status__in=OrderStatus.reserving_values()
        ).select_related("order").order_by("order__updated_at", "created_at", "pk")
        for item in order_items:
            events.append((item.order.updated_at, 2, item.pk, "order", item))

        events.sort(key=lambda event: (event[0], event[1], event[2]))

        for _effective_at, _sort_group, _source_pk, source_type, source in events:
            quantity = (source.quantity or Decimal("0.000")).quantize(Decimal("0.001"))
            if source_type == "adjustment":
                movement_type = source.movement_type
                if movement_type in cls.positive_values():
                    balance = (balance + quantity).quantize(Decimal("0.001"))
                else:
                    balance = (balance - quantity).quantize(Decimal("0.001"))
                if balance < 0:
                    balance = Decimal("0.000")
                movements.append(
                    cls(
                        roll=roll,
                        movement_type=movement_type,
                        quantity=quantity,
                        balance_after=balance,
                        stock_adjustment=source,
                        effective_at=source.created_at,
                    )
                )
                continue

            balance = (balance - quantity).quantize(Decimal("0.001"))
            if balance < 0:
                balance = Decimal("0.000")
            movements.append(
                cls(
                    roll=roll,
                    movement_type=(
                        StockMovementType.CONFIRMED
                        if source.order.status == OrderStatus.CONFIRMED
                        else StockMovementType.RESERVED
                    ),
                    quantity=quantity,
                    balance_after=balance,
                    order=source.order,
                    order_item=source,
                    effective_at=source.order.updated_at,
                )
            )

        cls.objects.bulk_create(movements)

    def __str__(self):
        return f"{self.get_movement_type_display()} | {self.roll.identifier} | {self.quantity}"
