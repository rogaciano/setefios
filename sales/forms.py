import json
import re
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.forms import BaseFormSet, BaseInlineFormSet, formset_factory, inlineformset_factory

from core.models import Company, Participant, Supplier

from .models import (
    Category,
    Color,
    FabricRoll,
    Order,
    OrderItem,
    Product,
    ProductUnit,
    ProductVariant,
    StockAdjustment,
    StockAdjustmentType,
    StockEntry,
    OrderStatus,
)


BASE_INPUT_CLASS = (
    "mt-2 block w-full rounded-2xl border border-stone-300 bg-white "
    "px-4 py-3 text-sm text-stone-900 shadow-sm outline-none "
    "transition focus:border-orange-500 focus:ring-2 focus:ring-orange-200"
)


def _text_widget(placeholder=""):
    return forms.TextInput(
        attrs={
            "class": BASE_INPUT_CLASS,
            "placeholder": placeholder,
        }
    )


def _number_widget(step="1", min_value="0"):
    return forms.NumberInput(
        attrs={
            "class": BASE_INPUT_CLASS,
            "step": step,
            "min": min_value,
        }
    )


def _textarea_widget(rows=3, placeholder=""):
    return forms.Textarea(
        attrs={
            "class": BASE_INPUT_CLASS,
            "rows": rows,
            "placeholder": placeholder,
        }
    )


def _select_widget():
    return forms.Select(attrs={"class": BASE_INPUT_CLASS})


def _multi_select_widget():
    return forms.SelectMultiple(
        attrs={
            "class": (
                "mt-2 block min-h-32 w-full rounded-2xl border border-stone-300 "
                "bg-white px-4 py-3 text-sm text-stone-900 shadow-sm outline-none "
                "transition focus:border-orange-500 focus:ring-2 focus:ring-orange-200"
            )
        }
    )


def _date_widget():
    return forms.DateInput(
        format="%Y-%m-%d",
        attrs={
            "class": BASE_INPUT_CLASS,
            "type": "date",
        }
    )


def _file_widget(accept=""):
    attrs = {"class": BASE_INPUT_CLASS}
    if accept:
        attrs["accept"] = accept
    return forms.ClearableFileInput(attrs=attrs)


def _split_names(raw_value):
    if not raw_value:
        return []
    tokens = re.split(r"[,;\n]+", raw_value)
    return [token.strip().upper() for token in tokens if token.strip()]


class VariantChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.label


class RollChoiceField(forms.ModelChoiceField):
    def __init__(self, *args, **kwargs):
        self.context_order = None
        super().__init__(*args, **kwargs)

    def label_from_instance(self, obj):
        available = obj.sellable_quantity(exclude_order=self.context_order)
        return (
            f"{obj.identifier} | {obj.variant.product.reference} | {obj.variant.color.name} | "
            f"Saldo {available:.3f} {obj.unit_code}"
        )


class ProductForm(forms.ModelForm):
    new_category_name = forms.CharField(
        label="Nova categoria",
        required=False,
        widget=_text_widget("Crie uma categoria sem sair da tela"),
    )
    new_colors = forms.CharField(
        label="Novas cores",
        required=False,
        widget=_textarea_widget(rows=2, placeholder="Ex.: Azul petróleo, Preto, Off White"),
        help_text="Separe por virgula, ponto e virgula ou quebra de linha.",
    )

    class Meta:
        model = Product
        fields = (
            "reference",
            "description",
            "price",
            "unit",
            "category",
            "colors",
            "is_active",
        )
        widgets = {
            "reference": _text_widget("Ex.: TEC-001"),
            "description": _text_widget("Nome do tecido"),
            "price": _number_widget(step="0.01", min_value="0.00"),
            "unit": _select_widget(),
            "category": _select_widget(),
            "colors": _multi_select_widget(),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        self.fields["unit"].initial = self.instance.unit or ProductUnit.METER
        self.fields["category"].required = False
        self.fields["colors"].required = False
        self.fields["category"].queryset = Category.objects.all()
        self.fields["colors"].queryset = Color.objects.all()
        self.fields["is_active"].widget.attrs.update(
            {
                "class": "h-5 w-5 rounded border-stone-300 text-orange-600 focus:ring-orange-500"
            }
        )

    def clean(self):
        cleaned_data = super().clean()
        reference = (cleaned_data.get("reference") or "").strip().upper()
        if reference:
            existing_products = Product.objects.filter(reference=reference)
            if self.instance.pk:
                existing_products = existing_products.exclude(pk=self.instance.pk)
            if existing_products.exists():
                self.add_error("reference", "Ja existe um produto com essa referencia.")

        if not cleaned_data.get("category") and not cleaned_data.get("new_category_name"):
            self.add_error("category", "Selecione ou crie uma categoria.")
        if not cleaned_data.get("colors") and not cleaned_data.get("new_colors"):
            self.add_error("colors", "Selecione ou informe pelo menos uma cor.")
        return cleaned_data

    def save(self, commit=True):
        category = self.cleaned_data.get("category")
        if not category and self.cleaned_data.get("new_category_name"):
            category, _ = Category.objects.get_or_create(
                name=self.cleaned_data["new_category_name"].strip().upper(),
            )

        product = super().save(commit=False)
        product.category = category
        if product.pk:
            product.updated_by = self.user
        else:
            product.created_by = self.user

        if commit:
            product.save()

            colors = list(self.cleaned_data.get("colors", []))
            for color_name in _split_names(self.cleaned_data.get("new_colors")):
                color, _ = Color.objects.get_or_create(name=color_name)
                colors.append(color)

            product.colors.set({color.pk: color for color in colors}.values())
            product.sync_variants()

        return product


class StockEntryForm(forms.ModelForm):
    class Meta:
        model = StockEntry
        fields = ("supplier", "received_at", "notes")
        widgets = {
            "supplier": _select_widget(),
            "received_at": _date_widget(),
            "notes": _textarea_widget(placeholder="Observacoes da entrada"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.filter(is_active=True).order_by("trade_name")


class PurchaseImportUploadForm(forms.Form):
    document = forms.FileField(
        label="Documento",
        widget=_file_widget('.pdf,.xml,.xlsx'),
        help_text="Envie um PDF, XML ou XLSX do fornecedor para diagnosticar a entrada.",
    )

    def clean_document(self):
        document = self.cleaned_data["document"]
        file_name = (document.name or "").lower()
        if not file_name.endswith((".pdf", ".xml", ".xlsx")):
            raise ValidationError("Envie um arquivo PDF, XML ou XLSX.")
        return document


class StockAdjustmentForm(forms.ModelForm):
    class Meta:
        model = StockAdjustment
        fields = ("adjustment_type", "quantity", "notes")
        widgets = {
            "adjustment_type": _select_widget(),
            "quantity": _number_widget(step="0.001", min_value="0.001"),
            "notes": _textarea_widget(rows=3, placeholder="Motivo do ajuste ou da devolucao"),
        }

    def __init__(self, *args, roll=None, **kwargs):
        self.roll = roll
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        adjustment_type = cleaned_data.get("adjustment_type")
        quantity = cleaned_data.get("quantity")

        if not self.roll or not adjustment_type or not quantity:
            return cleaned_data

        if adjustment_type == StockAdjustmentType.ADJUSTMENT_OUT:
            available_quantity = self.roll.sellable_quantity()
            if quantity > available_quantity:
                self.add_error(
                    "quantity",
                    f"O rolo {self.roll.identifier} possui saldo disponivel de {available_quantity:.3f} {self.roll.unit_code}.",
                )

        return cleaned_data


class ProductChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.reference} | {obj.description} | {obj.get_unit_display()}"


class StockEntryProductForm(forms.Form):
    product = ProductChoiceField(
        queryset=Product.objects.none(),
        label="Produto",
        required=False,
        widget=_select_widget(),
    )
    rolls_payload = forms.CharField(required=False, widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(is_active=True).order_by("reference", "description")


class BaseStockEntryProductFormSet(BaseFormSet):
    def __init__(self, *args, entry=None, **kwargs):
        self.entry = entry
        self.cleaned_rows = []
        self.removed_roll_ids = set()
        super().__init__(*args, **kwargs)

    def _parse_payload(self, payload_raw, product, entry_rolls, row_number):
        if not payload_raw or str(payload_raw).strip() in {"", "[]"}:
            return []

        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Os rolos informados na linha {row_number} estao invalidos.") from exc

        if not isinstance(payload, list):
            raise ValidationError(f"Os rolos informados na linha {row_number} estao invalidos.")

        variants = {
            variant.pk: variant
            for variant in ProductVariant.objects.filter(product=product).select_related("product", "color")
        }
        parsed_rolls = []
        seen_roll_ids = set()

        for position, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                raise ValidationError(f"Os rolos informados na linha {row_number} estao invalidos.")

            variant_raw = item.get("variant_id")
            roll_id_raw = item.get("id")
            identifier = str(item.get("identifier") or "").strip()
            quantity_raw = str(item.get("quantity") or "").strip().replace(",", ".")
            notes = str(item.get("notes") or "").strip()

            if not any([variant_raw, roll_id_raw, identifier, quantity_raw, notes]):
                continue

            if not variant_raw:
                raise ValidationError(
                    f"Selecione a cor de todos os rolos na linha {row_number}."
                )

            try:
                variant_id = int(variant_raw)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    f"A cor de um dos rolos da linha {row_number} esta invalida."
                ) from exc

            variant = variants.get(variant_id)
            if not variant:
                raise ValidationError(
                    f"A cor informada na linha {row_number} nao pertence ao produto selecionado."
                )

            if not quantity_raw:
                raise ValidationError(
                    f"Informe a quantidade de todos os rolos na linha {row_number}."
                )

            try:
                quantity = Decimal(quantity_raw)
            except Exception as exc:
                raise ValidationError(
                    f"A quantidade do rolo {position} na linha {row_number} esta invalida."
                ) from exc

            if quantity <= 0:
                raise ValidationError(
                    f"A quantidade do rolo {position} na linha {row_number} deve ser maior que zero."
                )

            quantity = quantity.quantize(Decimal("0.001"))
            existing_roll = None

            if roll_id_raw not in (None, ""):
                try:
                    roll_id = int(roll_id_raw)
                except (TypeError, ValueError) as exc:
                    raise ValidationError(
                        f"Um dos rolos da linha {row_number} esta invalido."
                    ) from exc

                if roll_id in seen_roll_ids:
                    raise ValidationError(
                        f"O mesmo rolo foi repetido na linha {row_number}."
                    )
                seen_roll_ids.add(roll_id)

                existing_roll = entry_rolls.get(roll_id)
                if not existing_roll:
                    raise ValidationError(
                        f"O rolo informado na linha {row_number} nao pertence a esta entrada."
                    )

                if existing_roll.variant_id != variant.pk and existing_roll.order_items.filter(
                    order__status__in=OrderStatus.reserving_values()
                ).exists():
                    raise ValidationError(
                        f"O rolo {existing_roll.identifier} ja foi usado em pedidos e nao pode mudar de cor."
                    )

                reserved_quantity = existing_roll.reserved_quantity()
                if quantity < reserved_quantity:
                    raise ValidationError(
                        f"O rolo {existing_roll.identifier} ja possui {reserved_quantity:.3f} {existing_roll.unit_code} reservado em pedidos."
                    )

            parsed_rolls.append(
                {
                    "id": existing_roll.pk if existing_roll else None,
                    "instance": existing_roll,
                    "variant": variant,
                    "quantity": quantity,
                    "notes": notes,
                }
            )

        return parsed_rolls

    def clean(self):
        super().clean()
        self.cleaned_rows = []
        entry_rolls = {}
        if self.entry and self.entry.pk:
            entry_rolls = {
                roll.pk: roll
                for roll in self.entry.rolls.select_related("variant__product", "variant__color")
            }

        has_product = False
        used_products = set()
        kept_roll_ids = set()

        for row_number, form in enumerate(self.forms, start=1):
            if not hasattr(form, "cleaned_data"):
                continue

            product = form.cleaned_data.get("product")
            payload_raw = (form.cleaned_data.get("rolls_payload") or "").strip()

            if not product and payload_raw in {"", "[]"}:
                continue

            if not product:
                raise ValidationError(f"Selecione o produto na linha {row_number}.")

            if product.pk in used_products:
                raise ValidationError(
                    f"O produto {product.reference} foi informado mais de uma vez na entrada."
                )
            used_products.add(product.pk)

            parsed_rolls = self._parse_payload(payload_raw, product, entry_rolls, row_number)
            if not parsed_rolls:
                raise ValidationError(
                    f"Adicione pelo menos um rolo para o produto da linha {row_number}."
                )

            has_product = True
            for roll in parsed_rolls:
                if roll["id"]:
                    kept_roll_ids.add(roll["id"])

            self.cleaned_rows.append(
                {
                    "product": product,
                    "rolls": parsed_rolls,
                }
            )

        if not has_product:
            raise ValidationError("Adicione pelo menos um produto com rolos na entrada.")

        self.removed_roll_ids = set(entry_rolls) - kept_roll_ids
        for roll_id in self.removed_roll_ids:
            roll = entry_rolls[roll_id]
            if roll.order_items.filter(order__status__in=OrderStatus.reserving_values()).exists():
                raise ValidationError(
                    f"O rolo {roll.identifier} ja foi usado em pedidos e nao pode ser removido."
                )


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = (
            "buyer_company",
            "participant",
            "representative",
            "status",
            "delivery_deadline",
            "freight_type",
            "carrier",
            "payment_method",
            "payment_terms",
            "discount_type",
            "discount_value",
            "notes",
        )
        widgets = {
            "buyer_company": _select_widget(),
            "participant": _select_widget(),
            "representative": _select_widget(),
            "status": _select_widget(),
            "delivery_deadline": _text_widget("Ex.: 15 dias"),
            "freight_type": _select_widget(),
            "carrier": _text_widget("Transportadora"),
            "payment_method": _text_widget("Ex.: Boleto"),
            "payment_terms": _text_widget("Ex.: 30/60/90"),
            "discount_type": _select_widget(),
            "discount_value": _number_widget(step="0.01"),
            "notes": _textarea_widget(placeholder="Observacoes do pedido"),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["buyer_company"].label = "Cliente"
        self.fields["participant"].label = "Contato do cliente"
        self.fields["representative"].required = False
        self.fields["buyer_company"].queryset = Company.objects.filter(is_active=True).order_by("trade_name", "legal_name")
        self.fields["participant"].queryset = Participant.objects.filter(is_active=True).order_by("name")
        self.fields["representative"].queryset = Participant.objects.filter(
            is_active=True,
            is_representative=True,
        ).order_by("name")

    def clean(self):
        cleaned_data = super().clean()
        buyer_company = cleaned_data.get("buyer_company")
        participant = cleaned_data.get("participant")

        if (
            buyer_company
            and participant
            and not participant.companies.filter(pk=buyer_company.pk).exists()
        ):
            self.add_error(
                "participant",
                "Selecione um contato vinculado ao cliente informado.",
            )

        representative = cleaned_data.get("representative")
        if representative and not representative.is_representative:
            self.add_error(
                "representative",
                "Selecione um participante marcado como representante.",
            )

        return cleaned_data

    def clean_discount_value(self):
        value = self.cleaned_data["discount_value"]
        return value or 0


class OrderItemForm(forms.ModelForm):
    roll = RollChoiceField(
        queryset=FabricRoll.objects.none(),
        label="Rolo",
        widget=_select_widget(),
    )

    class Meta:
        model = OrderItem
        fields = ("roll", "quantity", "unit_price", "notes")
        widgets = {
            "quantity": _number_widget(step="0.001", min_value="0.001"),
            "unit_price": _number_widget(step="0.01", min_value="0.00"),
            "notes": _text_widget("Observacao opcional"),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["roll"].required = False
        self.fields["quantity"].required = False
        self.fields["unit_price"].required = False
        self.fields["quantity"].widget.attrs["placeholder"] = "0,000"
        self.fields["unit_price"].widget.attrs["placeholder"] = "0,00"
        for field_name in ("quantity", "unit_price"):
            css_class = self.fields[field_name].widget.attrs.get("class", "")
            self.fields[field_name].widget.attrs.update(
                {
                    "readonly": "readonly",
                    "aria-readonly": "true",
                    "class": f"{css_class} bg-stone-50 text-stone-600".strip(),
                }
            )
        self.context_order = self.instance.order if self.instance.pk else None
        if not self.is_bound and not self.instance.pk:
            self.initial["quantity"] = ""
            self.initial["unit_price"] = ""
        queryset = FabricRoll.objects.filter(
            variant__is_active=True,
            variant__product__is_active=True,
        ).select_related(
            "variant__product",
            "variant__color",
            "stock_entry__supplier",
        )
        if self.instance.roll_id:
            queryset = queryset.filter(Q(available_quantity__gt=0) | Q(pk=self.instance.roll_id))
            if not self.is_bound:
                fixed_quantity = self.instance.roll.sellable_quantity(exclude_order=self.context_order)
                self.initial["quantity"] = fixed_quantity
                self.initial["unit_price"] = self.instance.roll.variant.product.price
        else:
            queryset = queryset.filter(available_quantity__gt=0)
        self.fields["roll"].queryset = queryset.order_by(
            "variant__product__reference",
            "variant__color__name",
            "identifier",
        )
        self.fields["roll"].context_order = self.context_order

    def clean(self):
        cleaned_data = super().clean()
        roll = cleaned_data.get("roll")

        if not roll:
            return cleaned_data

        fixed_quantity = roll.sellable_quantity(exclude_order=self.context_order)
        if fixed_quantity <= 0:
            self.add_error(
                "roll",
                f"O rolo {roll.identifier} nao possui saldo disponivel para venda.",
            )
            return cleaned_data

        cleaned_data["quantity"] = fixed_quantity
        cleaned_data["unit_price"] = roll.variant.product.price
        return cleaned_data


class BaseOrderItemFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        has_item = False
        current_order = self.instance if self.instance and self.instance.pk else None
        requested_by_roll = {}
        roll_map = {}

        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if form.cleaned_data.get("DELETE"):
                continue

            roll = form.cleaned_data.get("roll")
            quantity = form.cleaned_data.get("quantity")
            unit_price = form.cleaned_data.get("unit_price")
            notes = form.cleaned_data.get("notes")

            if roll and quantity:
                has_item = True
                requested_by_roll[roll.pk] = requested_by_roll.get(roll.pk, Decimal("0.000")) + quantity
                roll_map[roll.pk] = roll
                continue

            if roll or quantity or unit_price or notes:
                raise ValidationError("Preencha rolo e quantidade em cada linha usada.")

        if not has_item:
            raise ValidationError("Adicione pelo menos um item ao pedido.")

        for roll_id, requested_quantity in requested_by_roll.items():
            roll = roll_map[roll_id]
            available_quantity = roll.sellable_quantity(exclude_order=current_order)
            if requested_quantity > available_quantity:
                raise ValidationError(
                    f"O rolo {roll.identifier} possui saldo disponivel de {available_quantity:.3f} {roll.unit_code}."
                )


OrderItemFormSet = inlineformset_factory(
    Order,
    OrderItem,
    form=OrderItemForm,
    formset=BaseOrderItemFormSet,
    extra=0,
    can_delete=True,
)

StockEntryProductFormSet = formset_factory(
    StockEntryProductForm,
    formset=BaseStockEntryProductFormSet,
    extra=8,
)



