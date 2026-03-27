from datetime import timedelta
import html
import json
import re
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from sales.models import Category, Color, Order, OrderStatus, Product, ProductUnit

from .models import WebpicConfiguration


class WebpicServiceError(Exception):
    pass


class WebpicValidationError(WebpicServiceError):
    pass


class WebpicService:
    def __init__(self, config=None):
        self.config = config or WebpicConfiguration.get_solo()

    def pending_orders(self):
        return (
            Order.objects.filter(
                webpic_integrated=False,
                status=OrderStatus.CONFIRMED,
            )
            .select_related("buyer_company", "participant", "representative")
            .prefetch_related(
                "items__roll__variant__product",
                "items__roll__variant__color",
                "items__variant__product",
                "items__variant__color",
            )
            .order_by("created_at")
        )

    def fetch_reference_options(self):
        self._ensure_credentials()
        return {
            "price_tables": self._ensure_list(self._home_get("tabelasprecos")),
            "employees": self._ensure_list(self._home_get("funcionarios")),
            "representatives": self._ensure_list(self._home_get("representantes")),
            "client_groups": self._ensure_list(self._home_get("gruposclientes")),
            "current_accounts": self._ensure_list(self._home_get("contascorrentes")),
        }

    def sync_products(self, user):
        if not self.config.price_table_id:
            raise WebpicValidationError("Informe a tabela de preco antes de importar os produtos.")

        table_code = self.resolve_price_table_code(self.config.price_table_id)
        products = self._ensure_list(
            self._home_get(
                "produtosacabados",
                {"codigoTabela": table_code},
            )
        )
        return self.sync_remote_products(
            products,
            user=user,
            allow_without_price=self.config.import_products_without_price,
        )

    @transaction.atomic
    def sync_remote_products(self, remote_products, user, allow_without_price=None):
        if allow_without_price is None:
            allow_without_price = self.config.import_products_without_price

        imported = []
        updated = []
        report = {
            "total_rows": len(remote_products),
            "processed_total": 0,
            "imported_total": 0,
            "updated_total": 0,
            "processed_without_price_total": 0,
            "skipped_total": 0,
            "skipped_no_price": 0,
            "skipped_no_grades": 0,
            "skipped_missing_reference": 0,
        }

        for row in remote_products:
            grades = self._ensure_list(row.get("Grades"))
            if not grades:
                report["skipped_total"] += 1
                report["skipped_no_grades"] += 1
                continue

            highest_price = max(
                (self._to_decimal(grade.get("Valor")) for grade in grades),
                default=Decimal("0.00"),
            )
            has_valid_price = highest_price > 0
            if not has_valid_price and not allow_without_price:
                report["skipped_total"] += 1
                report["skipped_no_price"] += 1
                continue

            reference = self._normalize_reference(row.get("Referencia"))
            if not reference:
                report["skipped_total"] += 1
                report["skipped_missing_reference"] += 1
                continue

            description = self._normalize_text(html.unescape(row.get("Descricao") or ""))
            category_name = self._normalize_text(row.get("Grupo") or "SEM GRUPO")
            category, _ = Category.objects.get_or_create(name=category_name)
            product = Product.objects.filter(reference=reference).first()
            created = product is None

            if created:
                product = Product(reference=reference, created_by=user)
            else:
                product.updated_by = user
                if not product.created_by_id:
                    product.created_by = user

            product.category = category
            product.description = description or reference
            product.unit = self._resolve_unit(row)
            if has_valid_price:
                product.price = highest_price
            elif created:
                product.price = Decimal("0.00")
            product.save()

            color_ids = set(product.colors.values_list("pk", flat=True))
            variant_barcodes = {}

            for grade in grades:
                color_name = self._normalize_text(grade.get("Cor"))
                if not color_name:
                    continue

                color, _ = Color.objects.get_or_create(name=color_name)
                color_ids.add(color.pk)

                barcode = (grade.get("CodigoBarras") or "").strip()
                if barcode and color.name not in variant_barcodes:
                    variant_barcodes[color.name] = barcode

            if color_ids:
                product.colors.set(color_ids)
            product.sync_variants()

            variants = {
                variant.color.name: variant
                for variant in product.variants.select_related("color")
            }
            changed_barcode = False
            for color_name, barcode in variant_barcodes.items():
                variant = variants.get(color_name)
                if not variant:
                    continue
                if variant.barcode != barcode:
                    variant.barcode = barcode
                    variant.save(update_fields=["barcode", "updated_at"])
                    changed_barcode = True

            summary = {
                "reference": product.reference,
                "description": product.description,
                "group": product.category.name,
                "barcode_changed": changed_barcode,
                "without_price": not has_valid_price,
            }
            if created:
                imported.append(summary)
            else:
                updated.append(summary)
            report["processed_total"] += 1
            if not has_valid_price:
                report["processed_without_price_total"] += 1

        report["imported_total"] = len(imported)
        report["updated_total"] = len(updated)
        return {
            "imported": imported,
            "updated": updated,
            "skipped": report["skipped_total"],
            "report": report,
        }

    def export_pending_orders(self):
        missing_fields = self.config.missing_export_fields()
        if missing_fields:
            raise WebpicValidationError(
                "Configuracao incompleta para exportacao: " + ", ".join(missing_fields)
            )

        pending_orders = list(self.pending_orders())
        if not pending_orders:
            return []

        access_token = self._ensure_access_token()
        results = []

        for order in pending_orders:
            payload = None
            try:
                payload = self.build_order_payload(order)
                response = self._sales_post(
                    "v1/pedidosvendassimples",
                    payload,
                    access_token=access_token,
                )
                if self._response_has_error(response):
                    message = response.get("Mensagem") or response.get("message") or "Erro retornado pela API."
                    order.webpic_payload = payload
                    order.webpic_response = response
                    order.webpic_integrated = False
                    order.save(
                        update_fields=[
                            "webpic_payload",
                            "webpic_response",
                            "webpic_integrated",
                            "updated_at",
                        ]
                    )
                    results.append({"status": "error", "order_id": order.pk, "message": message})
                    continue

                order.webpic_payload = payload
                order.webpic_response = response
                order.webpic_integrated = True
                order.webpic_exported_at = timezone.now()
                order.save(
                    update_fields=[
                        "webpic_payload",
                        "webpic_response",
                        "webpic_integrated",
                        "webpic_exported_at",
                        "updated_at",
                    ]
                )
                results.append(
                    {
                        "status": "success",
                        "order_id": order.pk,
                        "message": "Pedido exportado com sucesso.",
                    }
                )
            except WebpicServiceError as exc:
                order.webpic_payload = payload
                order.webpic_response = {"error": str(exc)}
                order.webpic_integrated = False
                order.save(
                    update_fields=[
                        "webpic_payload",
                        "webpic_response",
                        "webpic_integrated",
                        "updated_at",
                    ]
                )
                results.append({"status": "error", "order_id": order.pk, "message": str(exc)})

        return results

    def build_order_payload(self, order):
        missing_fields = self.config.missing_export_fields()
        if missing_fields:
            raise WebpicValidationError(
                "Configuracao incompleta para gerar o payload: " + ", ".join(missing_fields)
            )

        if not order.items.exists():
            raise WebpicValidationError(f"O pedido #{order.pk} nao possui itens para exportacao.")

        products = []
        for item in order.items.select_related(
            "roll__variant__product",
            "roll__variant__color",
            "variant__product",
            "variant__color",
        ):
            source_variant = item.source_variant
            if not source_variant:
                raise WebpicValidationError(
                    f"O item do pedido #{order.pk} nao possui variante valida para exportacao."
                )

            barcode = (source_variant.barcode or "").strip()
            if not barcode:
                label = item.roll.identifier if item.roll_id else source_variant.label
                raise WebpicValidationError(
                    f"O item {label} nao possui codigo de barras vinculado."
                )
            products.append(
                {
                    "Codigo": barcode,
                    "Quantidade": float(item.quantity),
                    "Valor": float(item.unit_price),
                }
            )

        company = order.buyer_company
        created_at = timezone.localtime(order.created_at)
        discount = self._calculate_discount(order)
        cnpj = self._only_digits(company.cnpj)

        return {
            "Codigo": str(order.pk),
            "Data": created_at.strftime("%d/%m/%Y"),
            "ValorFrete": 0,
            "ServicoFrete": order.carrier or "",
            "Desconto": float(discount),
            "Acrescimo": 0,
            "IdFuncionario": int(self.config.employee_id),
            "IdGrupoCliente": int(self.config.client_group_id),
            "IdRepresentante": int(self.config.representative_id),
            "IdTabelaPreco": int(self.config.price_table_id),
            "IdContaCorrente": int(self.config.current_account_id),
            "Cliente": {
                "RazaoSocial": company.legal_name,
                "Fantasia": company.trade_name or company.legal_name,
                "TipoPessoa": 1 if len(cnpj) == 14 else 0,
                "CpfCnpj": cnpj,
                "RgIe": self._only_digits(company.state_registration),
                "Telefone": self._only_digits(company.phone),
                "Email": company.email or "",
            },
            "Endereco": {
                "Logradouro": company.street or "",
                "Numero": company.number or "0",
                "Complemento": company.complement or "",
                "Bairro": company.district or "",
                "Cidade": company.city or "",
                "Estado": company.state or "",
                "Cep": self._only_digits(company.postal_code),
            },
            "Pagamentos": [
                {
                    "FormaPagamento": order.payment_method or "A COMBINAR",
                    "Parcelas": 1,
                    "ValorPago": float(order.total_amount),
                    "DataPagamento": created_at.strftime("%d/%m/%Y"),
                }
            ],
            "Produtos": products,
        }

    def resolve_price_table_code(self, table_id):
        tables = self._ensure_list(self._home_get("tabelasprecos"))
        for table in tables:
            if int(table.get("Id") or 0) == int(table_id):
                return table.get("Codigo") or table_id
        return table_id

    def _ensure_credentials(self):
        if not self.config.has_credentials:
            raise WebpicValidationError("Informe WEBPIC_API_COMPANY e WEBPIC_API_TOKEN no .env.")

    def _ensure_access_token(self):
        self._ensure_credentials()
        response = self._request_json(
            f"{settings.WEBPIC_SALES_API_BASE.rstrip('/')}/autenticacao/v1/login?empresa={self.config.resolved_api_company}&TokenIntegracao={self.config.resolved_api_token}",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "ApiSenhaBypassModulo": settings.WEBPIC_BYPASS_PASSWORD,
            },
        )
        access_token = response.get("access_token") if isinstance(response, dict) else None
        if not access_token:
            raise WebpicServiceError("Nao foi possivel autenticar na API da Webpic.")

        self.config.access_token = access_token
        self.config.access_token_expires_at = timezone.now() + timedelta(hours=23)
        self.config.save(update_fields=["access_token", "access_token_expires_at", "updated_at"])
        return access_token

    def _home_get(self, method, extra_params=None):
        self._ensure_credentials()
        params = {
            "empresa": self.config.resolved_api_company,
            "token": self.config.resolved_api_token,
        }
        if extra_params:
            params.update(extra_params)
        url = f"{settings.WEBPIC_HOME_API_BASE.rstrip('/')}/{method}?{urlencode(params)}"
        return self._request_json(url)

    def _sales_post(self, method, payload, access_token=None):
        token = access_token or self._ensure_access_token()
        return self._request_json(
            f"{settings.WEBPIC_SALES_API_BASE.rstrip('/')}/{method.lstrip('/')}",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "ApiSenhaBypassModulo": settings.WEBPIC_BYPASS_PASSWORD,
                "Authorization": f"Bearer {token}",
            },
            data=payload,
        )

    def _request_json(self, url, method="GET", headers=None, data=None):
        request_headers = headers or {}
        body = None
        if method.upper() == "POST":
            if data is None:
                body = b""
            else:
                body = json.dumps(data).encode("utf-8")

        request = Request(url, data=body, headers=request_headers, method=method.upper())
        try:
            with urlopen(request, timeout=30) as response:
                payload = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise WebpicServiceError(
                f"Erro HTTP na integracao Webpic ({exc.code}): {detail or exc.reason}"
            ) from exc
        except URLError as exc:
            raise WebpicServiceError(f"Falha de comunicacao com a Webpic: {exc.reason}") from exc
        except OSError as exc:
            raise WebpicServiceError(f"Nao foi possivel acessar a Webpic: {exc}") from exc

        if not payload:
            return {}

        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise WebpicServiceError("A Webpic retornou uma resposta invalida.") from exc

    def _response_has_error(self, response):
        if not isinstance(response, dict):
            return False
        status = str(response.get("Status") or response.get("status") or "").strip().lower()
        return status == "erro" or status == "error"

    def _ensure_list(self, value):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for key in ("data", "Data", "result", "Result"):
                if isinstance(value.get(key), list):
                    return value[key]
        return []

    def _calculate_discount(self, order):
        discount_value = order.discount_value or Decimal("0.00")
        if discount_value <= 0:
            return Decimal("0.00")
        if order.discount_type == "A":
            return discount_value
        return (order.subtotal_amount * discount_value) / Decimal("100.00")

    def _resolve_unit(self, row):
        raw_value = self._normalize_text(
            row.get("Unidade")
            or row.get("UnidadeMedida")
            or row.get("Medida")
            or row.get("TipoUnidade")
            or ""
        )
        if raw_value in {"KG", "KGS", "QUILO", "QUILOS", "PESO", "PESO (KG)"}:
            return ProductUnit.KILOGRAM
        return ProductUnit.METER

    def _normalize_text(self, value):
        return " ".join(str(value or "").strip().upper().split())

    def _normalize_reference(self, value):
        return re.sub(r"\s+", "", str(value or "").strip().upper())

    def _only_digits(self, value):
        return re.sub(r"\D", "", str(value or ""))

    def _to_decimal(self, value):
        try:
            return Decimal(str(value or 0))
        except Exception:
            return Decimal("0.00")




