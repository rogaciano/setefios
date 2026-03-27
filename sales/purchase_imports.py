from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable
from zipfile import ZipFile
import re
import unicodedata
import xml.etree.ElementTree as ET

from .models import Product, ProductUnit


EXCEL_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
NFE_NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}
ZERO = Decimal("0.000")


@dataclass
class ImportedRollLine:
    external_code: str = ""
    quantity: Decimal = ZERO
    unit: str = ""
    unit_price: Decimal = Decimal("0.00")
    total_value: Decimal = Decimal("0.00")


@dataclass
class ImportedColorGroup:
    code: str = ""
    name: str = ""
    total_quantity: Decimal = ZERO
    rolls: list[ImportedRollLine] = field(default_factory=list)


@dataclass
class ImportedProductGroup:
    reference: str = ""
    description: str = ""
    unit: str = ""
    total_quantity: Decimal = ZERO
    colors: list[ImportedColorGroup] = field(default_factory=list)


@dataclass
class ParsedPurchaseDocument:
    parser_key: str
    source_name: str
    supplier_hint: str = ""
    note_number: str = ""
    warnings: list[str] = field(default_factory=list)
    products: list[ImportedProductGroup] = field(default_factory=list)


@dataclass
class ProductDiagnosis:
    reference: str
    description: str
    exists: bool
    product_id: int | None
    color_total: int
    roll_total: int


@dataclass
class DocumentAnalysisResult:
    document: ParsedPurchaseDocument
    diagnoses: list[ProductDiagnosis] = field(default_factory=list)

    @property
    def matched_total(self) -> int:
        return sum(1 for item in self.diagnoses if item.exists)


class PurchaseImportError(Exception):
    pass


@dataclass
class FaturamentoSheetProfile:
    parser_key: str
    supplier_hint_index: int
    summary_column: int
    product_summary_column: int
    roll_product_column: int
    roll_color_column: int
    roll_unit_column: int
    roll_quantity_column: int
    roll_code_column: int | None
    roll_value_column: int
    roll_unit_price_column: int


def normalize_token(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).upper()


def simplify_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return normalize_token(without_marks)


def normalize_reference(value: str) -> str:
    return normalize_token(value).replace(" ", "")


def normalize_unit(value: str) -> str:
    token = simplify_token(value)
    if token in {"M", "MT", "METRO", "METROS"}:
        return ProductUnit.METER
    if token in {"KG", "K", "QUILO", "QUILOS", "PESO", "PESO (KG)"}:
        return ProductUnit.KILOGRAM
    return normalize_token(value)


def split_code_and_name(value: str) -> tuple[str, str]:
    raw_value = normalize_token(value)
    if not raw_value:
        return "", ""
    if " - " in raw_value:
        code, name = raw_value.split(" - ", 1)
        return code.strip(), name.strip()
    return "", raw_value


def split_reference_and_description(value: str) -> tuple[str, str]:
    raw_value = normalize_token(value)
    if not raw_value:
        return "", ""
    if " - " in raw_value:
        reference, description = raw_value.split(" - ", 1)
        return normalize_reference(reference), description.strip()
    return normalize_reference(raw_value), raw_value


def to_decimal(value) -> Decimal:
    text = str(value or "").strip()
    if not text:
        return ZERO

    normalized = text.replace(" ", "")
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")

    try:
        number = Decimal(normalized)
    except (InvalidOperation, ValueError):
        return ZERO
    return number.quantize(Decimal("0.001"))


def to_money(value) -> Decimal:
    return to_decimal(value).quantize(Decimal("0.01"))


def col_to_index(column_ref: str) -> int:
    total = 0
    for char in column_ref:
        if char.isalpha():
            total = total * 26 + (ord(char.upper()) - 64)
    return max(total - 1, 0)


def iter_xlsx_rows(file_path: Path) -> Iterable[tuple[str, list[list[str]]]]:
    with ZipFile(file_path) as archive:
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("a:si", EXCEL_NS):
                parts = [node.text or "" for node in item.iterfind(".//a:t", EXCEL_NS)]
                shared_strings.append("".join(parts))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relationship_map = {
            relation.attrib["Id"]: relation.attrib["Target"]
            for relation in relationships
        }

        for sheet in workbook.find("a:sheets", EXCEL_NS):
            sheet_name = sheet.attrib["name"]
            relation_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            target = relationship_map[relation_id]
            if not target.startswith("xl/"):
                target = f"xl/{target}"

            root = ET.fromstring(archive.read(target))
            rows = []
            for row in root.findall(".//a:sheetData/a:row", EXCEL_NS):
                values = {}
                max_index = -1
                for cell in row.findall("a:c", EXCEL_NS):
                    ref = cell.attrib.get("r", "")
                    index = col_to_index("".join(char for char in ref if char.isalpha()))
                    max_index = max(max_index, index)
                    cell_type = cell.attrib.get("t")
                    if cell_type == "s":
                        value_node = cell.find("a:v", EXCEL_NS)
                        value = shared_strings[int(value_node.text)] if value_node is not None and value_node.text else ""
                    elif cell_type == "inlineStr":
                        value = "".join(node.text or "" for node in cell.iterfind(".//a:t", EXCEL_NS))
                    else:
                        value_node = cell.find("a:v", EXCEL_NS)
                        value = value_node.text if value_node is not None and value_node.text else ""
                    values[index] = value
                rows.append([values.get(idx, "") for idx in range(max_index + 1)])
            yield sheet_name, rows


def get_cell(row: list[str], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    return str(row[index] or "").strip()


def ensure_product(document: ParsedPurchaseDocument, reference: str, description: str, unit: str) -> ImportedProductGroup:
    normalized_reference = normalize_reference(reference)
    for product in document.products:
        if product.reference == normalized_reference:
            if not product.description and description:
                product.description = normalize_token(description)
            if not product.unit and unit:
                product.unit = normalize_unit(unit)
            return product

    product = ImportedProductGroup(
        reference=normalized_reference,
        description=normalize_token(description),
        unit=normalize_unit(unit),
    )
    document.products.append(product)
    return product


def ensure_color(product: ImportedProductGroup, code: str, name: str) -> ImportedColorGroup:
    normalized_code = normalize_token(code)
    normalized_name = normalize_token(name)
    for color in product.colors:
        if color.code == normalized_code and color.name == normalized_name:
            return color

    color = ImportedColorGroup(code=normalized_code, name=normalized_name)
    product.colors.append(color)
    return color


def extract_note_number(text: str) -> str:
    normalized = normalize_token(text)
    quoted_match = re.search(r"\bNOTA\b\s*:\s*'([^']+)'", normalized)
    if quoted_match:
        return normalize_token(quoted_match.group(1)).replace(" ", "")

    plain_match = re.search(r"\bNOTA\b\s*[:#-]?\s*([A-Z0-9./-]+)", normalized)
    if not plain_match:
        return ""

    candidate = normalize_token(plain_match.group(1)).replace(" ", "")
    if not any(char.isdigit() for char in candidate):
        return ""
    return candidate


def is_reference_description(value: str) -> bool:
    reference, description = split_reference_and_description(value)
    return bool(reference and description)


def build_error_result(file_path: Path, error: Exception) -> DocumentAnalysisResult:
    document = ParsedPurchaseDocument(
        parser_key="error",
        source_name=file_path.name,
        warnings=[str(error)],
    )
    return DocumentAnalysisResult(document=document)


FATURAMENTO_BASIC_PROFILE = FaturamentoSheetProfile(
    parser_key="faturamento_xlsx_basic",
    supplier_hint_index=7,
    summary_column=1,
    product_summary_column=-1,
    roll_product_column=4,
    roll_color_column=9,
    roll_unit_column=13,
    roll_quantity_column=17,
    roll_code_column=None,
    roll_value_column=27,
    roll_unit_price_column=23,
)

FATURAMENTO_LOTE_PROFILE = FaturamentoSheetProfile(
    parser_key="faturamento_xlsx_lote",
    supplier_hint_index=7,
    summary_column=1,
    product_summary_column=1,
    roll_product_column=4,
    roll_color_column=9,
    roll_unit_column=12,
    roll_quantity_column=22,
    roll_code_column=16,
    roll_value_column=30,
    roll_unit_price_column=26,
)


class PurchaseDocumentParser:
    parser_key = "base"
    supported_suffixes: tuple[str, ...] = ()

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.supported_suffixes

    def parse(self, file_path: Path) -> ParsedPurchaseDocument:
        raise NotImplementedError


class FaturamentoXlsxParser(PurchaseDocumentParser):
    parser_key = "faturamento_xlsx"
    supported_suffixes = (".xlsx",)

    def detect_profile(self, rows: list[list[str]]) -> FaturamentoSheetProfile:
        first_rows = rows[:12]
        flattened = [simplify_token(cell) for row in first_rows for cell in row if str(cell or "").strip()]
        if not any("RELATORIO DE PECAS FATURADAS - FATURAMENTO" in cell for cell in flattened):
            raise PurchaseImportError("Planilha XLSX nao corresponde ao relatorio de pecas faturadas suportado.")
        if any(cell == "LOTE" for cell in flattened):
            return FATURAMENTO_LOTE_PROFILE
        return FATURAMENTO_BASIC_PROFILE

    def parse(self, file_path: Path) -> ParsedPurchaseDocument:
        sheets = list(iter_xlsx_rows(file_path))
        if not sheets:
            raise PurchaseImportError("Planilha XLSX sem abas legiveis.")

        profile = self.detect_profile(sheets[0][1])
        document = ParsedPurchaseDocument(
            parser_key=profile.parser_key,
            source_name=file_path.name,
        )
        if profile.roll_code_column is None:
            document.warnings.append(
                "Este layout nao traz codigo externo do rolo. O sistema vai gerar identificadores proprios na entrada."
            )

        for _sheet_name, rows in sheets:
            if not document.supplier_hint:
                for row in rows[:6]:
                    supplier_hint = get_cell(row, profile.supplier_hint_index)
                    if supplier_hint:
                        document.supplier_hint = normalize_token(supplier_hint)
                        break

            if not document.note_number:
                for row in rows[:10]:
                    for cell in row:
                        note_number = extract_note_number(cell)
                        if note_number:
                            document.note_number = note_number
                            break
                    if document.note_number:
                        break

            for row in rows:
                product_text = get_cell(row, profile.roll_product_column)
                color_text = get_cell(row, profile.roll_color_column)
                unit = normalize_unit(get_cell(row, profile.roll_unit_column))
                quantity = to_decimal(get_cell(row, profile.roll_quantity_column))
                if not (product_text and color_text and unit and quantity > ZERO):
                    continue
                if not is_reference_description(product_text):
                    continue

                reference, description = split_reference_and_description(product_text)
                color_code, color_name = split_code_and_name(color_text)
                if not reference or not color_name:
                    continue

                product = ensure_product(document, reference, description, unit)
                color = ensure_color(product, color_code, color_name)
                roll = ImportedRollLine(
                    external_code=get_cell(row, profile.roll_code_column) if profile.roll_code_column is not None else "",
                    quantity=quantity,
                    unit=unit,
                    unit_price=to_money(get_cell(row, profile.roll_unit_price_column)),
                    total_value=to_money(get_cell(row, profile.roll_value_column)),
                )
                color.rolls.append(roll)
                color.total_quantity = (color.total_quantity + quantity).quantize(Decimal("0.001"))
                product.total_quantity = (product.total_quantity + quantity).quantize(Decimal("0.001"))

        if not document.products:
            raise PurchaseImportError("Nenhum produto foi extraido da planilha XLSX.")
        return document


class NFeXmlParser(PurchaseDocumentParser):
    parser_key = "nfe_xml"
    supported_suffixes = (".xml",)

    def parse(self, file_path: Path) -> ParsedPurchaseDocument:
        if not file_path.exists() or file_path.stat().st_size == 0:
            raise PurchaseImportError("Arquivo XML vazio ou indisponivel.")

        try:
            root = ET.parse(file_path).getroot()
        except ET.ParseError as exc:
            raise PurchaseImportError(f"Falha ao ler XML: {exc}") from exc

        emit_name = root.findtext(".//nfe:emit/nfe:xNome", default="", namespaces=NFE_NS)
        note_number = root.findtext(".//nfe:ide/nfe:nNF", default="", namespaces=NFE_NS)
        document = ParsedPurchaseDocument(
            parser_key=self.parser_key,
            source_name=file_path.name,
            supplier_hint=normalize_token(emit_name),
            note_number=normalize_token(note_number),
        )
        document.warnings.append(
            "XML NF-e foi lido em nivel de item. Cor e rolos nao aparecem nesse layout e vao precisar de complemento manual."
        )

        for item in root.findall(".//nfe:det", NFE_NS):
            product_node = item.find("nfe:prod", NFE_NS)
            if product_node is None:
                continue
            reference = product_node.findtext("nfe:cProd", default="", namespaces=NFE_NS)
            description = product_node.findtext("nfe:xProd", default="", namespaces=NFE_NS)
            unit = normalize_unit(product_node.findtext("nfe:uCom", default="", namespaces=NFE_NS))
            quantity = to_decimal(product_node.findtext("nfe:qCom", default="", namespaces=NFE_NS))
            unit_price = to_money(product_node.findtext("nfe:vUnCom", default="", namespaces=NFE_NS))
            total_value = to_money(product_node.findtext("nfe:vProd", default="", namespaces=NFE_NS))
            if not reference:
                continue

            product = ensure_product(document, reference, description, unit)
            product.total_quantity = (product.total_quantity + quantity).quantize(Decimal("0.001"))
            if quantity > ZERO:
                product.colors.append(
                    ImportedColorGroup(
                        code="",
                        name="",
                        total_quantity=quantity,
                        rolls=[
                            ImportedRollLine(
                                external_code="",
                                quantity=quantity,
                                unit=unit,
                                unit_price=unit_price,
                                total_value=total_value,
                            )
                        ],
                    )
                )

        if not document.products:
            raise PurchaseImportError("Nenhum item foi extraido do XML NF-e.")
        return document


class PendingPdfParser(PurchaseDocumentParser):
    parser_key = "pdf_pending"
    supported_suffixes = (".pdf",)

    def parse(self, file_path: Path) -> ParsedPurchaseDocument:
        document = ParsedPurchaseDocument(
            parser_key=self.parser_key,
            source_name=file_path.name,
        )
        document.warnings.append(
            "PDF reconhecido, mas a extracao de texto ainda depende de um parser especifico. Use o XLSX/XML equivalente quando existir."
        )
        return document


class PurchaseDocumentAnalyzer:
    def __init__(self, parsers: list[PurchaseDocumentParser] | None = None):
        self.parsers = parsers or [
            FaturamentoXlsxParser(),
            NFeXmlParser(),
            PendingPdfParser(),
        ]

    @property
    def supported_suffixes(self) -> set[str]:
        return {
            suffix
            for parser in self.parsers
            for suffix in parser.supported_suffixes
        }

    def get_parser(self, file_path: Path) -> PurchaseDocumentParser:
        for parser in self.parsers:
            if parser.can_parse(file_path):
                return parser
        raise PurchaseImportError(f"Formato nao suportado para importacao: {file_path.suffix}")

    def diagnose_document(self, document: ParsedPurchaseDocument) -> list[ProductDiagnosis]:
        catalog = {
            normalize_reference(product.reference): product
            for product in Product.objects.only("id", "reference")
        }
        diagnoses = []
        for imported in document.products:
            matched_product = catalog.get(normalize_reference(imported.reference))
            diagnoses.append(
                ProductDiagnosis(
                    reference=imported.reference,
                    description=imported.description,
                    exists=matched_product is not None,
                    product_id=matched_product.pk if matched_product else None,
                    color_total=len([color for color in imported.colors if color.name]),
                    roll_total=sum(len(color.rolls) for color in imported.colors),
                )
            )
        return diagnoses

    def analyze_file(self, file_path: Path) -> DocumentAnalysisResult:
        parser = self.get_parser(file_path)
        document = parser.parse(file_path)
        diagnoses = self.diagnose_document(document)
        return DocumentAnalysisResult(document=document, diagnoses=diagnoses)

    def analyze_directory(self, base_path: Path | str) -> list[DocumentAnalysisResult]:
        path = Path(base_path)
        if not path.exists():
            raise PurchaseImportError(f"Caminho nao encontrado: {path}")

        if path.is_file():
            files = [path]
        else:
            files = [
                child
                for child in sorted(path.iterdir(), key=lambda item: item.name.lower())
                if child.is_file() and child.suffix.lower() in self.supported_suffixes
            ]

        results = []
        for file_path in files:
            try:
                results.append(self.analyze_file(file_path))
            except Exception as exc:
                results.append(build_error_result(file_path, exc))
        return results
