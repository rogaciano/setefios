import json
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.models import Supplier, SupplierImportProfile

from .forms import (
    OrderForm,
    OrderItemFormSet,
    ProductForm,
    PurchaseImportUploadForm,
    StockAdjustmentForm,
    StockEntryForm,
    StockEntryProductFormSet,
)
from .models import FabricRoll, Order, Product, ProductUnit, StockAdjustmentType, StockEntry, StockMovement, StockMovementType
from .purchase_imports import PurchaseDocumentAnalyzer, PurchaseImportError, extract_note_number, normalize_reference, simplify_token


IMPORT_PREVIEW_SESSION_KEY = "stock_entry_import_preview"
IMPORT_DRAFT_SESSION_KEY = "stock_entry_import_draft"
ZERO_QUANTITY = Decimal("0.000")


def _build_stock_entry_formset_initial(entry):
    grouped_rows = {}
    rolls = entry.rolls.select_related(
        "variant__product",
        "variant__color",
    ).order_by(
        "variant__product__reference",
        "variant__color__name",
        "identifier",
    )

    for roll in rolls:
        product = roll.variant.product
        row = grouped_rows.setdefault(
            product.pk,
            {
                "product": product.pk,
                "rolls": [],
            },
        )
        row["rolls"].append(
            {
                "id": roll.pk,
                "identifier": roll.identifier,
                "variant_id": roll.variant_id,
                "variant_label": roll.variant.color.name,
                "quantity": f"{roll.initial_quantity:.3f}",
                "notes": roll.notes,
            }
        )

    return [
        {
            "product": row["product"],
            "rolls_payload": json.dumps(row["rolls"], ensure_ascii=False),
        }
        for row in grouped_rows.values()
    ]


def _build_product_catalog():
    catalog = []
    products = Product.objects.filter(is_active=True).prefetch_related(
        "variants__color",
    ).order_by("reference", "description")

    for product in products:
        variants = [
            {
                "id": variant.pk,
                "color_name": variant.color.name,
                "label": variant.label,
                "unit_code": product.unit,
                "unit_display": product.get_unit_display(),
            }
            for variant in product.variants.select_related("color").filter(is_active=True).order_by("color__name")
        ]
        if not variants:
            continue

        catalog.append(
            {
                "id": product.pk,
                "reference": product.reference,
                "description": product.description,
                "label": f"{product.reference} | {product.description}",
                "unit_code": product.unit,
                "unit_display": product.get_unit_display(),
                "variants": variants,
            }
        )

    return catalog


def _decorate_roll_stock(roll):
    roll.adjustment_total = roll.adjustment_delta()
    roll.physical_total = roll.physical_quantity()
    roll.available_quantity = (roll.available_quantity or Decimal("0.000")).quantize(Decimal("0.001"))
    roll.reserved_total = (roll.physical_total - roll.available_quantity).quantize(Decimal("0.001"))
    if roll.reserved_total < 0:
        roll.reserved_total = Decimal("0.000")

    if roll.available_quantity <= 0:
        roll.stock_status = "sold_out"
    elif roll.reserved_total > 0:
        roll.stock_status = "reserved"
    else:
        roll.stock_status = "available"
    return roll


def _build_variant_rows_from_rolls(rolls):
    grouped = {}
    for roll in rolls:
        row = grouped.setdefault(
            roll.variant_id,
            {
                "variant_id": roll.variant_id,
                "variant__product__reference": roll.variant.product.reference,
                "variant__product__description": roll.variant.product.description,
                "variant__product__unit": roll.variant.product.unit,
                "variant__color__name": roll.variant.color.name,
                "unit_display": roll.unit_display,
                "roll_total": 0,
                "adjustment_total": Decimal("0.000"),
                "physical_total": Decimal("0.000"),
                "reserved_total": Decimal("0.000"),
                "available_total": Decimal("0.000"),
            },
        )
        row["roll_total"] += 1
        row["adjustment_total"] += roll.adjustment_total
        row["physical_total"] += roll.physical_total
        row["reserved_total"] += roll.reserved_total
        row["available_total"] += roll.available_quantity

    return sorted(
        grouped.values(),
        key=lambda row: (row["variant__product__reference"], row["variant__color__name"]),
    )


def _build_stock_overview_url(query="", unit="", status="", product="", color=""):
    params = {}
    if query:
        params["q"] = query
    if unit in {ProductUnit.METER, ProductUnit.KILOGRAM}:
        params["unit"] = unit
    if status in {"available", "reserved", "sold_out"}:
        params["status"] = status
    if product:
        params["product"] = product
    if color:
        params["color"] = color

    base_url = reverse("sales:stock_overview")
    return f"{base_url}?{urlencode(params)}" if params else base_url


def _build_product_groups_from_rolls(rolls, query="", unit="", status=""):
    grouped = {}
    for roll in rolls:
        product = roll.variant.product
        product_key = normalize_reference(product.reference)
        group = grouped.setdefault(
            product_key,
            {
                "key": product_key,
                "reference": product.reference,
                "description": product.description,
                "unit_code": product.unit,
                "unit_display": roll.unit_display,
                "roll_total": 0,
                "color_total": 0,
                "adjustment_total": Decimal("0.000"),
                "physical_total": Decimal("0.000"),
                "reserved_total": Decimal("0.000"),
                "available_total": Decimal("0.000"),
                "colors": {},
            },
        )
        group["roll_total"] += 1
        group["adjustment_total"] += roll.adjustment_total
        group["physical_total"] += roll.physical_total
        group["reserved_total"] += roll.reserved_total
        group["available_total"] += roll.available_quantity

        color_key = str(roll.variant_id)
        color_row = group["colors"].setdefault(
            color_key,
            {
                "variant_id": color_key,
                "name": roll.variant.color.name,
                "roll_total": 0,
                "adjustment_total": Decimal("0.000"),
                "physical_total": Decimal("0.000"),
                "reserved_total": Decimal("0.000"),
                "available_total": Decimal("0.000"),
            },
        )
        color_row["roll_total"] += 1
        color_row["adjustment_total"] += roll.adjustment_total
        color_row["physical_total"] += roll.physical_total
        color_row["reserved_total"] += roll.reserved_total
        color_row["available_total"] += roll.available_quantity

    groups = []
    for product_key in sorted(grouped, key=lambda key: (grouped[key]["reference"], grouped[key]["description"])):
        group = grouped[product_key]
        colors = sorted(group["colors"].values(), key=lambda item: item["name"])
        group["colors"] = colors
        group["color_total"] = len(colors)
        group["select_url"] = _build_stock_overview_url(query=query, unit=unit, status=status, product=group["reference"])
        for color in colors:
            color["select_url"] = _build_stock_overview_url(
                query=query,
                unit=unit,
                status=status,
                product=group["reference"],
                color=color["variant_id"],
            )
        groups.append(group)

    return groups


def _scope_rolls_for_browser(rolls, product_groups, selected_product, selected_color):
    if not product_groups:
        return [], None, None

    normalized_product = normalize_reference(selected_product)
    active_product = next((group for group in product_groups if group["key"] == normalized_product), None)
    if active_product is None:
        active_product = product_groups[0]

    active_color = None
    selected_color_token = str(selected_color or "").strip()
    if selected_color_token:
        active_color = next(
            (color for color in active_product["colors"] if color["variant_id"] == selected_color_token),
            None,
        )

    scoped_rolls = [
        roll
        for roll in rolls
        if normalize_reference(roll.variant.product.reference) == active_product["key"]
    ]
    if active_color:
        scoped_rolls = [roll for roll in scoped_rolls if str(roll.variant_id) == active_color["variant_id"]]

    for group in product_groups:
        group["is_selected"] = group["key"] == active_product["key"]
        for color in group["colors"]:
            color["is_selected"] = bool(
                group["is_selected"] and active_color and color["variant_id"] == active_color["variant_id"]
            )

    return scoped_rolls, active_product, active_color


def _normalize_roll_scan_code(raw_code):
    code = str(raw_code or "").strip().upper()
    if not code:
        return ""
    code = code.replace(" ", "")
    if code.startswith("ROLO"):
        for separator in (":", "Ç"):
            prefix = f"ROLO{separator}"
            if code.startswith(prefix):
                code = code.split(separator, 1)[1]
                break
    return code.strip()


def _tokenize_profile_keywords(raw_value):
    return [
        simplify_token(token)
        for token in str(raw_value or "").replace(";", ",").split(",")
        if simplify_token(token)
    ]


def _score_supplier_import_profile(profile, document):
    document_parser_key = (document.parser_key or "").strip().upper()
    if profile.parser_key and profile.parser_key != document_parser_key:
        return 0

    score = 0
    if profile.parser_key:
        score += 40

    supplier_hint = simplify_token(document.supplier_hint)
    if profile.supplier_hint_pattern:
        pattern = simplify_token(profile.supplier_hint_pattern)
        if supplier_hint == pattern:
            score += 100
        elif supplier_hint and (pattern in supplier_hint or supplier_hint in pattern):
            score += 70
        else:
            return 0

    file_tokens = _tokenize_profile_keywords(profile.file_name_tokens)
    if file_tokens:
        source_name = simplify_token(document.source_name)
        matched_tokens = [token for token in file_tokens if token in source_name]
        if not matched_tokens:
            return 0
        score += 15 * len(matched_tokens)

    if not score:
        return 0
    return score


def _find_supplier_by_profile(document):
    profiles = SupplierImportProfile.objects.select_related("supplier").filter(
        is_active=True,
        supplier__is_active=True,
    )
    ranked = []
    for profile in profiles:
        score = _score_supplier_import_profile(profile, document)
        if score > 0:
            ranked.append((score, profile.match_count, profile.pk, profile))

    if not ranked:
        return None

    ranked.sort(reverse=True)
    return ranked[0][3]


def _find_supplier_for_hint(supplier_hint):
    hint = simplify_token(supplier_hint)
    if not hint:
        return None

    suppliers = list(Supplier.objects.filter(is_active=True).only("id", "trade_name"))
    for supplier in suppliers:
        if simplify_token(supplier.trade_name) == hint:
            return supplier

    for supplier in suppliers:
        supplier_name = simplify_token(supplier.trade_name)
        if supplier_name and (supplier_name in hint or hint in supplier_name):
            return supplier

    return None


def _resolve_supplier_for_document(document):
    matched_profile = _find_supplier_by_profile(document)
    if matched_profile:
        return matched_profile.supplier, matched_profile
    return _find_supplier_for_hint(document.supplier_hint), None


def _remember_import_profile(imported_draft):
    supplier_id = imported_draft.get("supplier")
    if not supplier_id:
        return

    matched_profile_id = imported_draft.get("matched_profile_id")
    if matched_profile_id:
        profile = SupplierImportProfile.objects.select_related("supplier").filter(
            pk=matched_profile_id,
            supplier_id=supplier_id,
        ).first()
        if profile:
            profile.register_match()
            return

    supplier = Supplier.objects.filter(pk=supplier_id, is_active=True).first()
    if not supplier:
        return

    supplier_hint = (imported_draft.get("supplier_hint") or "").strip().upper()
    parser_key = (imported_draft.get("parser_key") or "").strip().upper()
    if not supplier_hint and not parser_key:
        return

    profile, _created = SupplierImportProfile.objects.get_or_create(
        supplier=supplier,
        parser_key=parser_key,
        supplier_hint_pattern=supplier_hint,
        file_name_tokens="",
        defaults={
            "name": f"AUTO {parser_key or 'IMPORTACAO'}",
            "is_active": True,
        },
    )
    profile.register_match()


def _match_variant_by_color(product, imported_color_name):
    target = simplify_token(imported_color_name)
    if not target:
        return None

    variants = [
        variant
        for variant in product.variants.select_related("color").all()
        if variant.is_active
    ]
    exact_map = {
        simplify_token(variant.color.name): variant
        for variant in variants
    }
    if target in exact_map:
        return exact_map[target]

    for variant_name, variant in exact_map.items():
        if variant_name and (variant_name in target or target in variant_name):
            return variant

    return None


def _build_import_roll_note(imported_roll):
    note_parts = []
    if imported_roll.external_code:
        note_parts.append(f"Lote externo: {imported_roll.external_code}")
    return " | ".join(note_parts)


def _normalize_note_number(note_number):
    return simplify_token(note_number).replace(" ", "")


def _get_stock_entry_note_number(entry):
    return _normalize_note_number(entry.source_note_number) or extract_note_number(entry.notes)


def _empty_signature_bucket(reference, unit):
    return {
        "reference": normalize_reference(reference),
        "unit": unit or "",
        "total_quantity": ZERO_QUANTITY,
        "roll_total": 0,
        "colors": {},
    }


def _accumulate_signature_roll(products_map, reference, unit, color_name, quantity, roll_total=1):
    normalized_reference = normalize_reference(reference)
    if not normalized_reference:
        return

    product_bucket = products_map.setdefault(normalized_reference, _empty_signature_bucket(normalized_reference, unit))
    if unit and not product_bucket["unit"]:
        product_bucket["unit"] = unit

    normalized_color = simplify_token(color_name)
    color_bucket = product_bucket["colors"].setdefault(
        normalized_color,
        {
            "name": normalized_color,
            "total_quantity": ZERO_QUANTITY,
            "roll_total": 0,
        },
    )

    quantized_quantity = (quantity or ZERO_QUANTITY).quantize(Decimal("0.001"))
    color_bucket["total_quantity"] = (color_bucket["total_quantity"] + quantized_quantity).quantize(Decimal("0.001"))
    color_bucket["roll_total"] += roll_total
    product_bucket["total_quantity"] = (product_bucket["total_quantity"] + quantized_quantity).quantize(Decimal("0.001"))
    product_bucket["roll_total"] += roll_total


def _finalize_signature(products_map):
    products = []
    total_quantity = ZERO_QUANTITY
    total_rolls = 0

    for reference in sorted(products_map):
        product_bucket = products_map[reference]
        colors = []
        for color_name in sorted(product_bucket["colors"]):
            color_bucket = product_bucket["colors"][color_name]
            colors.append(
                {
                    "name": color_bucket["name"],
                    "total_quantity": f"{color_bucket['total_quantity']:.3f}",
                    "roll_total": color_bucket["roll_total"],
                }
            )

        products.append(
            {
                "reference": product_bucket["reference"],
                "unit": product_bucket["unit"],
                "total_quantity": f"{product_bucket['total_quantity']:.3f}",
                "roll_total": product_bucket["roll_total"],
                "color_total": len(colors),
                "colors": colors,
            }
        )
        total_quantity = (total_quantity + product_bucket["total_quantity"]).quantize(Decimal("0.001"))
        total_rolls += product_bucket["roll_total"]

    return {
        "product_total": len(products),
        "roll_total": total_rolls,
        "total_quantity": f"{total_quantity:.3f}",
        "products": products,
    }


def _build_document_signature(document):
    products_map = {}
    for imported_product in document.products:
        if imported_product.colors:
            for imported_color in imported_product.colors:
                if imported_color.rolls:
                    for roll in imported_color.rolls:
                        _accumulate_signature_roll(
                            products_map,
                            imported_product.reference,
                            imported_product.unit,
                            imported_color.name,
                            roll.quantity,
                            1,
                        )
                    continue

                if imported_color.total_quantity > ZERO_QUANTITY:
                    _accumulate_signature_roll(
                        products_map,
                        imported_product.reference,
                        imported_product.unit,
                        imported_color.name,
                        imported_color.total_quantity,
                        0,
                    )
            continue

        if imported_product.total_quantity > ZERO_QUANTITY:
            _accumulate_signature_roll(
                products_map,
                imported_product.reference,
                imported_product.unit,
                "",
                imported_product.total_quantity,
                0,
            )

    return _finalize_signature(products_map)


def _build_cleaned_rows_signature(cleaned_rows):
    products_map = {}
    for row in cleaned_rows:
        product = row.get("product")
        if not product:
            continue

        for roll_data in row.get("rolls", []):
            variant = roll_data["variant"]
            _accumulate_signature_roll(
                products_map,
                variant.product.reference,
                variant.product.unit,
                variant.color.name,
                roll_data["quantity"],
                1,
            )

    return _finalize_signature(products_map)


def _build_saved_entry_signature(entry):
    products_map = {}
    for roll in entry.rolls.all():
        _accumulate_signature_roll(
            products_map,
            roll.variant.product.reference,
            roll.variant.product.unit,
            roll.variant.color.name,
            roll.initial_quantity,
            1,
        )

    return _finalize_signature(products_map)


def _build_duplicate_check_payload(status, entry, note_number):
    entry_note_number = _get_stock_entry_note_number(entry) or _normalize_note_number(note_number)
    if status == "exact":
        title = "Documento ja importado"
        if entry_note_number:
            message = (
                f"A entrada #{entry.pk} do fornecedor {entry.supplier.trade_name} "
                f"ja usa a nota {entry_note_number} com os mesmos produtos e totais."
            )
        else:
            message = (
                f"A entrada #{entry.pk} do fornecedor {entry.supplier.trade_name} "
                "ja tem os mesmos produtos, rolos e totais deste documento."
            )
    elif status == "note":
        title = "Nota ja cadastrada"
        message = (
            f"A entrada #{entry.pk} do fornecedor {entry.supplier.trade_name} "
            f"ja usa a nota {entry_note_number}. Revise antes de importar novamente."
        )
    else:
        title = "Produtos e totais ja cadastrados"
        message = (
            f"A entrada #{entry.pk} do fornecedor {entry.supplier.trade_name} "
            "ja tem os mesmos produtos, rolos e totais deste documento."
        )

    return {
        "status": status,
        "title": title,
        "message": message,
        "entry_id": entry.pk,
        "entry_label": f"Entrada #{entry.pk}",
        "entry_url": reverse("sales:stock_entry_update", args=[entry.pk]),
    }


def _find_duplicate_stock_entry(supplier, note_number, signature, exclude_entry_id=None):
    if not supplier:
        return None

    normalized_note_number = _normalize_note_number(note_number)
    has_signature = bool(signature.get("products"))
    if not normalized_note_number and not has_signature:
        return None

    entries = (
        StockEntry.objects.filter(supplier=supplier)
        .exclude(pk=exclude_entry_id)
        .prefetch_related("rolls__variant__product", "rolls__variant__color")
        .order_by("-received_at", "-pk")
    )

    note_conflict = None
    signature_conflict = None
    for candidate in entries:
        candidate_note_number = _get_stock_entry_note_number(candidate)
        candidate_signature = _build_saved_entry_signature(candidate)
        note_matches = bool(normalized_note_number and candidate_note_number == normalized_note_number)
        signature_matches = bool(has_signature and candidate_signature == signature)

        if note_matches and signature_matches:
            return _build_duplicate_check_payload("exact", candidate, normalized_note_number)
        if note_matches and note_conflict is None:
            note_conflict = candidate
        if signature_matches and signature_conflict is None:
            signature_conflict = candidate

    if note_conflict:
        return _build_duplicate_check_payload("note", note_conflict, normalized_note_number)
    if signature_conflict:
        return _build_duplicate_check_payload("signature", signature_conflict, normalized_note_number)
    return None


def _build_import_preview(result):
    document = result.document
    references = [normalize_reference(product.reference) for product in document.products if product.reference]
    products = Product.objects.filter(is_active=True).prefetch_related("variants__color")
    product_map = {
        normalize_reference(product.reference): product
        for product in products
        if normalize_reference(product.reference) in references
    }
    suggested_supplier, matched_profile = _resolve_supplier_for_document(document)
    document_signature = _build_document_signature(document)
    duplicate_check = _find_duplicate_stock_entry(
        supplier=suggested_supplier,
        note_number=document.note_number,
        signature=document_signature,
    )
    rows = []
    items = []

    for imported_product in document.products:
        local_product = product_map.get(normalize_reference(imported_product.reference))
        issues = []
        matched_colors = []
        missing_colors = []
        document_colors = []
        roll_payload = []
        roll_total = sum(len(color.rolls) for color in imported_product.colors)
        imported_color_names = [color.name for color in imported_product.colors if color.name]

        if not local_product:
            issues.append("Referencia nao encontrada no cadastro de produtos.")
        else:
            if imported_product.unit and local_product.unit != imported_product.unit:
                expected_unit = dict(ProductUnit.choices).get(imported_product.unit, imported_product.unit)
                issues.append(
                    f"Unidade do arquivo ({expected_unit}) difere da unidade do cadastro ({local_product.get_unit_display()})."
                )

        for imported_color in imported_product.colors:
            if not imported_color.name:
                continue

            variant = _match_variant_by_color(local_product, imported_color.name) if local_product else None
            document_colors.append(
                {
                    "code": imported_color.code,
                    "name": imported_color.name,
                    "total_quantity": f"{imported_color.total_quantity:.3f}",
                    "roll_total": len(imported_color.rolls),
                    "is_matched": bool(variant),
                }
            )

            if not local_product:
                continue
            if not variant:
                missing_colors.append(imported_color.name)
                continue

            matched_colors.append(imported_color.name)
            for roll in imported_color.rolls:
                roll_payload.append(
                    {
                        "variant_id": variant.pk,
                        "identifier": "",
                        "quantity": f"{roll.quantity:.3f}",
                        "notes": _build_import_roll_note(roll),
                    }
                )

        if local_product and imported_product.colors and missing_colors:
            issues.append(
                "Cores sem variante cadastrada no produto: " + ", ".join(sorted(set(missing_colors))) + "."
            )
        if local_product and not imported_color_names:
            issues.append("O documento nao traz rolos por cor, entao a entrada nao pode ser montada automaticamente.")
        if local_product and imported_color_names and not roll_payload:
            issues.append("Nenhum rolo conseguiu ser associado a uma cor cadastrada.")

        ready = bool(local_product and not issues and roll_payload)
        if ready:
            rows.append(
                {
                    "product": local_product.pk,
                    "rolls_payload": json.dumps(roll_payload, ensure_ascii=False),
                }
            )

        items.append(
            {
                "reference": imported_product.reference,
                "description": imported_product.description,
                "document_unit": imported_product.unit,
                "document_unit_label": dict(ProductUnit.choices).get(imported_product.unit, imported_product.unit or "-"),
                "product_exists": bool(local_product),
                "product_label": (
                    f"{local_product.reference} | {local_product.description}"
                    if local_product
                    else ""
                ),
                "color_total": len(document_colors),
                "roll_total": roll_total,
                "total_quantity": f"{imported_product.total_quantity:.3f}",
                "document_colors": document_colors,
                "matched_colors": matched_colors,
                "missing_colors": missing_colors,
                "issues": issues,
                "ready": ready,
            }
        )

    note_parts = [f"Importado de {document.source_name}"]
    if document.note_number:
        note_parts.append(f"Nota {document.note_number}")

    preview = {
        "source_name": document.source_name,
        "parser_key": document.parser_key,
        "supplier_hint": document.supplier_hint,
        "suggested_supplier_id": suggested_supplier.pk if suggested_supplier else "",
        "suggested_supplier_label": suggested_supplier.trade_name if suggested_supplier else "",
        "matched_profile_id": matched_profile.pk if matched_profile else "",
        "matched_profile_label": matched_profile.name if matched_profile else "",
        "matched_by_profile": bool(matched_profile),
        "note_number": document.note_number,
        "warnings": document.warnings,
        "duplicate_check": duplicate_check,
        "product_total": len(items),
        "ready_total": sum(1 for item in items if item["ready"]),
        "missing_total": sum(1 for item in items if item["issues"]),
        "roll_total": sum(item["roll_total"] for item in items),
        "can_apply": bool(items) and all(item["ready"] for item in items) and not duplicate_check,
        "items": items,
        "draft": {
            "supplier": suggested_supplier.pk if suggested_supplier else "",
            "received_at": timezone.localdate().isoformat(),
            "notes": " | ".join(note_parts),
            "rows": rows,
            "source_name": document.source_name,
            "parser_key": document.parser_key,
            "supplier_hint": document.supplier_hint,
            "matched_profile_id": matched_profile.pk if matched_profile else "",
            "note_number": document.note_number,
            "warnings": document.warnings,
        },
    }
    return preview


def _analyze_uploaded_document(uploaded_file):
    suffix = Path(uploaded_file.name or "documento").suffix or ".tmp"
    with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        for chunk in uploaded_file.chunks():
            temp_file.write(chunk)
        temp_path = Path(temp_file.name)

    try:
        result = PurchaseDocumentAnalyzer().analyze_file(temp_path)
        result.document.source_name = uploaded_file.name
    finally:
        temp_path.unlink(missing_ok=True)

    return _build_import_preview(result)


@login_required
def product_list(request):
    query = request.GET.get("q", "").strip()
    products = (
        Product.objects.all()
        .select_related("category")
        .prefetch_related("colors", "variants")
        .order_by("description")
    )

    if query:
        products = products.filter(
            Q(reference__icontains=query) | Q(description__icontains=query)
        )

    return render(
        request,
        "sales/product_list.html",
        {
            "products": products,
            "query": query,
        },
    )


@login_required
def product_form(request, pk=None):
    product = None
    if pk:
        product = get_object_or_404(Product, pk=pk)

    form = ProductForm(request.POST or None, instance=product, user=request.user)

    if request.method == "POST" and form.is_valid():
        form.save()
        action = "atualizado" if product else "cadastrado"
        messages.success(request, f"Produto {action} com sucesso.")
        return redirect("sales:product_list")

    return render(
        request,
        "sales/product_form.html",
        {
            "form": form,
            "product": product,
        },
    )


@login_required
def stock_entry_list(request):
    query = request.GET.get("q", "").strip()
    entries = (
        StockEntry.objects.select_related("supplier")
        .annotate(roll_total=Count("rolls"))
        .order_by("-received_at", "-pk")
    )

    if query:
        entries = entries.filter(
            Q(supplier__trade_name__icontains=query)
            | Q(source_note_number__icontains=query)
            | Q(notes__icontains=query)
            | Q(pk__icontains=query)
        )

    return render(
        request,
        "sales/stock_entry_list.html",
        {
            "entries": entries,
            "query": query,
        },
    )


@login_required
def stock_overview(request):
    query = request.GET.get("q", "").strip()
    unit = request.GET.get("unit", "").strip()
    status = request.GET.get("status", "").strip()
    selected_product = request.GET.get("product", "").strip()
    selected_color = request.GET.get("color", "").strip()

    rolls_qs = FabricRoll.objects.select_related(
        "variant__product",
        "variant__color",
        "stock_entry__supplier",
    ).prefetch_related("adjustments").order_by(
        "variant__product__reference",
        "variant__color__name",
        "identifier",
    )

    if query:
        rolls_qs = rolls_qs.filter(
            Q(identifier__icontains=query)
            | Q(variant__product__reference__icontains=query)
            | Q(variant__product__description__icontains=query)
            | Q(variant__color__name__icontains=query)
            | Q(stock_entry__supplier__trade_name__icontains=query)
        )

    if unit in {ProductUnit.METER, ProductUnit.KILOGRAM}:
        rolls_qs = rolls_qs.filter(variant__product__unit=unit)

    rolls = [_decorate_roll_stock(roll) for roll in rolls_qs]

    if status == "available":
        rolls = [roll for roll in rolls if roll.stock_status == "available"]
    elif status == "reserved":
        rolls = [roll for roll in rolls if roll.stock_status == "reserved"]
    elif status == "sold_out":
        rolls = [roll for roll in rolls if roll.stock_status == "sold_out"]

    variant_rows = _build_variant_rows_from_rolls(rolls)
    product_groups = _build_product_groups_from_rolls(rolls, query=query, unit=unit, status=status)
    scoped_rolls, active_product, active_color = _scope_rolls_for_browser(
        rolls,
        product_groups,
        selected_product,
        selected_color,
    )

    summary = {
        "variant_total": len(variant_rows),
        "roll_total": len(rolls),
        "available_roll_total": sum(1 for roll in rolls if roll.available_quantity > 0),
        "reserved_roll_total": sum(1 for roll in rolls if roll.stock_status == "reserved"),
        "sold_out_roll_total": sum(1 for roll in rolls if roll.stock_status == "sold_out"),
    }

    return render(
        request,
        "sales/stock_overview.html",
        {
            "query": query,
            "unit": unit,
            "status": status,
            "variant_rows": variant_rows,
            "product_groups": product_groups,
            "rolls": scoped_rolls,
            "active_product": active_product,
            "active_color": active_color,
            "summary": summary,
            "unit_choices": ProductUnit.choices,
        },
    )


@login_required
def stock_movement_list(request):
    query = request.GET.get("q", "").strip()
    movement_type = request.GET.get("movement_type", "").strip()

    movements_qs = StockMovement.objects.select_related(
        "roll__variant__product",
        "roll__variant__color",
        "roll__stock_entry__supplier",
        "stock_entry",
        "stock_adjustment",
        "order",
    ).order_by("-effective_at", "-pk")

    if query:
        filters = (
            Q(roll__identifier__icontains=query)
            | Q(roll__variant__product__reference__icontains=query)
            | Q(roll__variant__product__description__icontains=query)
            | Q(roll__variant__color__name__icontains=query)
            | Q(roll__stock_entry__supplier__trade_name__icontains=query)
            | Q(stock_adjustment__notes__icontains=query)
        )
        if query.isdigit():
            filters |= (
                Q(order_id=int(query))
                | Q(stock_entry_id=int(query))
                | Q(stock_adjustment_id=int(query))
            )
        movements_qs = movements_qs.filter(filters)

    if movement_type in StockMovementType.values:
        movements_qs = movements_qs.filter(movement_type=movement_type)

    movements = list(movements_qs)
    summary = {
        "movement_total": len(movements),
        "roll_total": len({movement.roll_id for movement in movements}),
        "entry_quantity": sum(
            (movement.quantity for movement in movements if movement.movement_type == StockMovementType.ENTRY),
            Decimal("0.000"),
        ).quantize(Decimal("0.001")),
        "adjustment_in_quantity": sum(
            (movement.quantity for movement in movements if movement.movement_type == StockMovementType.ADJUSTMENT_IN),
            Decimal("0.000"),
        ).quantize(Decimal("0.001")),
        "adjustment_out_quantity": sum(
            (movement.quantity for movement in movements if movement.movement_type == StockMovementType.ADJUSTMENT_OUT),
            Decimal("0.000"),
        ).quantize(Decimal("0.001")),
        "return_quantity": sum(
            (movement.quantity for movement in movements if movement.movement_type == StockMovementType.RETURN),
            Decimal("0.000"),
        ).quantize(Decimal("0.001")),
        "reserved_quantity": sum(
            (movement.quantity for movement in movements if movement.movement_type == StockMovementType.RESERVED),
            Decimal("0.000"),
        ).quantize(Decimal("0.001")),
        "confirmed_quantity": sum(
            (movement.quantity for movement in movements if movement.movement_type == StockMovementType.CONFIRMED),
            Decimal("0.000"),
        ).quantize(Decimal("0.001")),
    }

    return render(
        request,
        "sales/stock_movement_list.html",
        {
            "query": query,
            "movement_type": movement_type,
            "movement_type_choices": StockMovementType.choices,
            "movements": movements,
            "summary": summary,
        },
    )


@login_required
def stock_adjustment_form(request, roll_pk):
    roll = get_object_or_404(
        FabricRoll.objects.select_related(
            "variant__product",
            "variant__color",
            "stock_entry__supplier",
        ).prefetch_related("adjustments"),
        pk=roll_pk,
    )
    form = StockAdjustmentForm(request.POST or None, roll=roll)

    if request.method == "POST" and form.is_valid():
        adjustment = form.save(commit=False)
        adjustment.roll = roll
        adjustment.created_by = request.user
        adjustment.save()
        messages.success(request, "Movimentacao manual registrada com sucesso.")
        return redirect(f"{reverse('sales:stock_movement_list')}?q={roll.identifier}")

    recent_movements = roll.movements.select_related("order", "stock_adjustment").order_by("-effective_at", "-pk")[:8]
    _decorate_roll_stock(roll)
    return render(
        request,
        "sales/stock_adjustment_form.html",
        {
            "form": form,
            "roll": roll,
            "recent_movements": recent_movements,
            "adjustment_type_choices": StockAdjustmentType.choices,
        },
    )


@login_required
def roll_lookup(request):
    raw_code = request.GET.get("code", "")
    normalized_code = _normalize_roll_scan_code(raw_code)
    if not normalized_code:
        return JsonResponse({"detail": "Informe um codigo para localizar o rolo."}, status=400)

    current_order = None
    order_id = request.GET.get("order_id", "").strip()
    if order_id.isdigit():
        current_order = Order.objects.filter(pk=int(order_id)).first()

    queryset = FabricRoll.objects.select_related(
        "variant__product",
        "variant__color",
        "stock_entry__supplier",
    ).prefetch_related("adjustments").filter(
        variant__is_active=True,
        variant__product__is_active=True,
    )

    if current_order:
        current_roll_ids = current_order.items.exclude(roll_id=None).values_list("roll_id", flat=True)
        queryset = queryset.filter(Q(available_quantity__gt=0) | Q(pk__in=current_roll_ids))
    else:
        queryset = queryset.filter(available_quantity__gt=0)

    roll = queryset.filter(identifier__iexact=normalized_code).first()
    if not roll and normalized_code.isdigit():
        roll = queryset.filter(pk=int(normalized_code)).first()

    if not roll:
        return JsonResponse({"detail": "Nenhum rolo disponivel foi encontrado para esse codigo."}, status=404)

    available_quantity = roll.sellable_quantity(exclude_order=current_order)
    return JsonResponse(
        {
            "id": roll.pk,
            "identifier": roll.identifier,
            "reference": roll.variant.product.reference,
            "description": roll.variant.product.description,
            "color": roll.variant.color.name,
            "supplier": roll.stock_entry.supplier.trade_name,
            "unit_code": roll.unit_code,
            "unit_display": roll.unit_display,
            "available_quantity": f"{available_quantity:.3f}",
            "unit_price": f"{roll.variant.product.price:.2f}",
            "label": roll.label,
        }
    )


@login_required
def stock_entry_import(request):
    preview = request.session.get(IMPORT_PREVIEW_SESSION_KEY)
    form = PurchaseImportUploadForm()

    if request.method == "POST":
        action = request.POST.get("action") or "upload"

        if action == "clear":
            request.session.pop(IMPORT_PREVIEW_SESSION_KEY, None)
            messages.success(request, "Previa da importacao removida.")
            return redirect("sales:stock_entry_import")

        if action == "apply":
            if not preview:
                messages.error(request, "Envie um documento antes de montar a entrada.")
                return redirect("sales:stock_entry_import")
            if preview.get("duplicate_check"):
                messages.error(request, preview["duplicate_check"]["message"])
                return redirect("sales:stock_entry_import")
            if not preview.get("can_apply"):
                messages.error(request, "Ainda existem pendencias no documento. Ajuste o cadastro antes de aplicar a entrada.")
                return redirect("sales:stock_entry_import")

            request.session[IMPORT_DRAFT_SESSION_KEY] = preview["draft"]
            messages.success(request, "Entrada montada a partir do documento. Revise os dados antes de salvar.")
            return redirect("sales:stock_entry_create")

        form = PurchaseImportUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                preview = _analyze_uploaded_document(form.cleaned_data["document"])
            except PurchaseImportError as exc:
                form.add_error("document", str(exc))
            except Exception as exc:
                form.add_error("document", f"Nao foi possivel analisar o arquivo: {exc}")
            else:
                request.session[IMPORT_PREVIEW_SESSION_KEY] = preview
                if preview.get("duplicate_check"):
                    messages.error(request, preview["duplicate_check"]["message"])
                else:
                    message = (
                        "Documento pronto para montar a entrada."
                        if preview.get("can_apply")
                        else "Documento analisado com pendencias de cadastro."
                    )
                    messages.success(request, message)
                return redirect("sales:stock_entry_import")

    return render(
        request,
        "sales/stock_entry_import.html",
        {
            "form": form,
            "preview": preview,
        },
    )


@login_required
def stock_entry_form(request, pk=None):
    entry = None
    if pk:
        entry = get_object_or_404(StockEntry, pk=pk)

    imported_draft = request.session.get(IMPORT_DRAFT_SESSION_KEY) if not entry else None
    form_initial = None
    initial_rows = None
    if entry:
        initial_rows = _build_stock_entry_formset_initial(entry)
    elif request.method == "GET" and imported_draft:
        form_initial = {
            "supplier": imported_draft.get("supplier") or None,
            "received_at": imported_draft.get("received_at") or timezone.localdate(),
            "notes": imported_draft.get("notes") or "",
        }
        initial_rows = imported_draft.get("rows") or None

    form = StockEntryForm(request.POST or None, instance=entry, initial=form_initial)
    formset = StockEntryProductFormSet(
        request.POST or None,
        initial=initial_rows,
        prefix="rows",
        entry=entry,
    )
    existing_rolls = []
    old_roll_ids = set(entry.rolls.values_list("pk", flat=True)) if entry else set()

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        note_number = _normalize_note_number((imported_draft or {}).get("note_number"))
        if not note_number and entry:
            note_number = _get_stock_entry_note_number(entry)

        duplicate_check = None
        if imported_draft or note_number:
            duplicate_check = _find_duplicate_stock_entry(
                supplier=form.cleaned_data["supplier"],
                note_number=note_number,
                signature=_build_cleaned_rows_signature(formset.cleaned_rows),
                exclude_entry_id=entry.pk if entry else None,
            )

        if duplicate_check:
            form.add_error(None, duplicate_check["message"])
        else:
            with transaction.atomic():
                saved_entry = form.save(commit=False)
                if imported_draft is not None:
                    saved_entry.source_note_number = note_number
                if not saved_entry.created_by_id:
                    saved_entry.created_by = request.user
                saved_entry.save()

                kept_roll_ids = set()
                for row in formset.cleaned_rows:
                    for roll_data in row["rolls"]:
                        instance = roll_data["instance"]
                        if instance:
                            updated_fields = []
                            if instance.variant_id != roll_data["variant"].pk:
                                instance.variant = roll_data["variant"]
                                updated_fields.append("variant")
                            if instance.initial_quantity != roll_data["quantity"]:
                                instance.initial_quantity = roll_data["quantity"]
                                updated_fields.append("initial_quantity")
                            if instance.notes != roll_data["notes"]:
                                instance.notes = roll_data["notes"]
                                updated_fields.append("notes")
                            if updated_fields:
                                instance.save(update_fields=updated_fields + ["updated_at"])
                            kept_roll_ids.add(instance.pk)
                            continue

                        created_roll = FabricRoll.objects.create(
                            stock_entry=saved_entry,
                            variant=roll_data["variant"],
                            initial_quantity=roll_data["quantity"],
                            notes=roll_data["notes"],
                        )
                        kept_roll_ids.add(created_roll.pk)

                rolls_to_delete = saved_entry.rolls.exclude(pk__in=kept_roll_ids)
                for roll in rolls_to_delete:
                    roll.delete()

                current_roll_ids = set(saved_entry.rolls.values_list("pk", flat=True))
                FabricRoll.refresh_many(old_roll_ids | current_roll_ids)

            if not entry and imported_draft:
                _remember_import_profile(imported_draft)
                request.session.pop(IMPORT_DRAFT_SESSION_KEY, None)
            messages.success(request, "Entrada de estoque salva com sucesso.")
            return redirect("sales:stock_entry_update", pk=saved_entry.pk)

    if entry:
        existing_rolls = entry.rolls.select_related(
            "variant__product",
            "variant__color",
        ).order_by("identifier")

    return render(
        request,
        "sales/stock_entry_form.html",
        {
            "form": form,
            "formset": formset,
            "entry": entry,
            "existing_rolls": existing_rolls,
            "product_catalog": _build_product_catalog(),
            "imported_draft": imported_draft,
        },
    )


@login_required
def stock_entry_labels(request, pk):
    entry = get_object_or_404(StockEntry.objects.select_related("supplier"), pk=pk)
    rolls = entry.rolls.select_related(
        "variant__product",
        "variant__color",
    ).order_by("identifier")
    return render(
        request,
        "sales/roll_labels.html",
        {
            "rolls": rolls,
            "label_title": f"Etiquetas da entrada #{entry.pk}",
            "label_subtitle": entry.supplier.trade_name,
        },
    )


@login_required
def roll_label(request, pk):
    roll = get_object_or_404(
        FabricRoll.objects.select_related(
            "stock_entry__supplier",
            "variant__product",
            "variant__color",
        ),
        pk=pk,
    )
    return render(
        request,
        "sales/roll_labels.html",
        {
            "rolls": [roll],
            "label_title": f"Etiqueta do rolo {roll.identifier}",
            "label_subtitle": roll.variant.product.description,
        },
    )


@login_required
def order_list(request):
    query = request.GET.get("q", "").strip()
    orders = (
        Order.objects.all()
        .select_related("buyer_company", "participant", "representative")
        .order_by("-created_at")
    )

    if query:
        filters = (
            Q(buyer_company__legal_name__icontains=query)
            | Q(buyer_company__trade_name__icontains=query)
            | Q(participant__name__icontains=query)
        )
        if query.isdigit():
            filters |= Q(pk=int(query))
        orders = orders.filter(filters)

    return render(
        request,
        "sales/order_list.html",
        {
            "orders": orders,
            "query": query,
        },
    )


@login_required
def order_form(request, pk=None):
    order = None
    if pk:
        order = get_object_or_404(Order, pk=pk)

    form = OrderForm(request.POST or None, instance=order, user=request.user)
    formset = OrderItemFormSet(
        request.POST or None,
        instance=order,
        form_kwargs={"user": request.user},
    )
    old_roll_ids = set(order.items.exclude(roll_id=None).values_list("roll_id", flat=True)) if order else set()

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            saved_order = form.save(commit=False)
            if order:
                saved_order.updated_by = request.user
            else:
                saved_order.created_by = request.user
            saved_order.save()

            formset.instance = saved_order
            items = formset.save(commit=False)
            for deleted_item in formset.deleted_objects:
                deleted_item.delete()

            for item in items:
                if not item.roll_id or not item.quantity:
                    continue
                item.order = saved_order
                item.save()

            saved_order.recalculate_totals()
            current_roll_ids = set(saved_order.items.exclude(roll_id=None).values_list("roll_id", flat=True))
            FabricRoll.refresh_many(old_roll_ids | current_roll_ids)

        action = "atualizado" if order else "cadastrado"
        messages.success(request, f"Pedido {action} com sucesso.")
        return redirect("sales:order_list")

    return render(
        request,
        "sales/order_form.html",
        {
            "form": form,
            "formset": formset,
            "order": order,
        },
    )
