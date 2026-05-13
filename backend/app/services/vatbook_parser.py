from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET


_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS = {"a": _MAIN_NS, "r": _REL_NS}

_ANNOTATION_TYPE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("sub acc statement", "sub_account_statement"),
    ("credit note", "credit_note"),
    ("settlement discounts", "settlement_discount"),
    ("subscription service", "subscription_service"),
    ("statement", "statement"),
    ("invoice", "invoice"),
    ("receipt", "receipt"),
    ("contract", "contract"),
)


@dataclass(slots=True)
class ParsedVatbookAnnotation:
    row_number: int
    label: str | None
    note: str
    annotation_type: str
    raw_cells: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedVatbookTransaction:
    row_number: int
    posted_account: str | None
    pub: str | None
    transaction_date: date | None
    description1: str | None
    description2: str | None
    debit_amount: Decimal | None
    credit_amount: Decimal | None
    transaction_type: str | None
    category: str | None
    resale_23_amount: Decimal | None
    non_resale_23_amount: Decimal | None
    non_resale_13_5_amount: Decimal | None
    non_resale_9_amount: Decimal | None
    non_resale_0_amount: Decimal | None
    annotations: list[ParsedVatbookAnnotation] = field(default_factory=list)
    raw_cells: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedVatbookWorkbook:
    workbook_path: Path
    sheet_name: str
    transactions: list[ParsedVatbookTransaction]


def excel_serial_to_date(value: str | int | float | None) -> date | None:
    if value in (None, ""):
        return None
    try:
        serial = int(float(value))
    except (TypeError, ValueError):
        return None
    return date(1899, 12, 30) + timedelta(days=serial)


def parse_decimal(value: str | int | float | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def infer_annotation_type(*, label: str | None, note: str) -> str:
    candidates = []
    if label:
        candidates.append(label.strip().lower())
    if note:
        candidates.append(note.strip().lower())

    for candidate in candidates:
        for pattern, normalized in _ANNOTATION_TYPE_PATTERNS:
            if pattern in candidate:
                return normalized

    return "note"


def list_sheet_names(workbook_path: str | Path) -> list[str]:
    workbook_path = Path(workbook_path)
    with ZipFile(workbook_path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        return [
            sheet.attrib.get("name", "")
            for sheet in workbook.findall("a:sheets/a:sheet", _NS)
        ]


def parse_vatbook_workbook(
    workbook_path: str | Path,
    *,
    sheet_name: str | None = None,
) -> ParsedVatbookWorkbook:
    workbook_path = Path(workbook_path)
    with ZipFile(workbook_path) as archive:
        shared_strings = _read_shared_strings(archive)
        target_sheet_name, sheet_target = _resolve_sheet_target(
            archive,
            requested_sheet_name=sheet_name,
        )
        rows = list(_iter_sheet_rows(archive, sheet_target, shared_strings))

    transactions: list[ParsedVatbookTransaction] = []
    current_transaction: ParsedVatbookTransaction | None = None

    for row_number, cells in rows:
        if _is_structural_row(cells):
            continue
        if _is_transaction_row(cells):
            if current_transaction is not None:
                transactions.append(current_transaction)
            current_transaction = ParsedVatbookTransaction(
                row_number=row_number,
                posted_account=_clean(cells.get("B")),
                pub=_clean(cells.get("C")),
                transaction_date=excel_serial_to_date(cells.get("D")),
                description1=_clean(cells.get("E")),
                description2=_clean(cells.get("F")),
                debit_amount=parse_decimal(cells.get("G")),
                credit_amount=parse_decimal(cells.get("H")),
                transaction_type=_clean(cells.get("I")),
                category=_clean(cells.get("J")),
                resale_23_amount=parse_decimal(cells.get("K")),
                non_resale_23_amount=parse_decimal(cells.get("L")),
                non_resale_13_5_amount=parse_decimal(cells.get("M")),
                non_resale_9_amount=parse_decimal(cells.get("N")),
                non_resale_0_amount=parse_decimal(cells.get("O")),
                raw_cells=dict(cells),
            )
            continue

        if current_transaction is None or not _is_annotation_row(cells):
            continue

        annotation = _parse_annotation(row_number=row_number, cells=cells)
        if annotation is not None:
            current_transaction.annotations.append(annotation)

    if current_transaction is not None:
        transactions.append(current_transaction)

    return ParsedVatbookWorkbook(
        workbook_path=workbook_path,
        sheet_name=target_sheet_name,
        transactions=transactions,
    )


def _resolve_sheet_target(
    archive: ZipFile,
    *,
    requested_sheet_name: str | None,
) -> tuple[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

    sheets = workbook.findall("a:sheets/a:sheet", _NS)
    if not sheets:
        raise ValueError("Workbook does not contain any sheets")

    target_sheet = None
    if requested_sheet_name is None:
        target_sheet = sheets[0]
    else:
        for sheet in sheets:
            if sheet.attrib.get("name") == requested_sheet_name:
                target_sheet = sheet
                break
        if target_sheet is None:
            available = ", ".join(sheet.attrib.get("name", "") for sheet in sheets)
            raise ValueError(
                f"Sheet '{requested_sheet_name}' was not found. Available sheets: {available}"
            )

    relationship_id = target_sheet.attrib[f"{{{_REL_NS}}}id"]
    target = rel_map[relationship_id]
    if not target.startswith("xl/"):
        target = f"xl/{target}"
    return target_sheet.attrib.get("name", ""), target


def _iter_sheet_rows(
    archive: ZipFile,
    sheet_target: str,
    shared_strings: list[str],
):
    worksheet = ET.fromstring(archive.read(sheet_target))
    for row in worksheet.findall("a:sheetData/a:row", _NS):
        row_number = int(row.attrib["r"])
        cells: dict[str, str] = {}
        for cell in row.findall("a:c", _NS):
            reference = cell.attrib.get("r", "")
            column = "".join(char for char in reference if char.isalpha())
            value = _read_cell_value(cell, shared_strings)
            if value is None:
                continue
            cells[column] = value
        if cells:
            yield row_number, cells


def _read_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    shared_strings_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    shared_strings: list[str] = []
    for item in shared_strings_root.findall("a:si", _NS):
        shared_strings.append(
            "".join(text.text or "" for text in item.iterfind(".//a:t", _NS))
        )
    return shared_strings


def _read_cell_value(cell: ET.Element, shared_strings: list[str]) -> str | None:
    value_node = cell.find("a:v", _NS)
    if value_node is None:
        return None

    raw_value = value_node.text or ""
    if cell.attrib.get("t") == "s":
        index = int(raw_value)
        if 0 <= index < len(shared_strings):
            return shared_strings[index]
    return raw_value


def _is_transaction_row(cells: dict[str, str]) -> bool:
    has_bank_context = bool(_clean(cells.get("B"))) and bool(_clean(cells.get("C")))
    has_date = excel_serial_to_date(cells.get("D")) is not None
    has_amount = parse_decimal(cells.get("G")) is not None or parse_decimal(cells.get("H")) is not None
    has_type_or_category = bool(_clean(cells.get("I"))) or bool(_clean(cells.get("J")))
    return has_bank_context and has_date and has_amount and has_type_or_category


def _is_annotation_row(cells: dict[str, str]) -> bool:
    if _is_transaction_row(cells):
        return False
    text = " ".join(
        value.strip()
        for key, value in cells.items()
        if key in {"D", "E", "F", "G"} and value and value.strip()
    )
    return bool(text)


def _is_structural_row(cells: dict[str, str]) -> bool:
    posted_account = (_clean(cells.get("B")) or "").lower()
    if posted_account == "posted account":
        return True
    if posted_account == "bankacc" and excel_serial_to_date(cells.get("D")) is None:
        return True

    date_label = (_clean(cells.get("D")) or "").lower()
    transaction_type = (_clean(cells.get("I")) or "").lower()
    if date_label == "date" and transaction_type in {"type", "transaction type"}:
        return True

    return False


def _parse_annotation(
    *,
    row_number: int,
    cells: dict[str, str],
) -> ParsedVatbookAnnotation | None:
    parts = [_clean(cells.get(column)) for column in ("D", "E", "F", "G")]
    parts = [part for part in parts if part]
    if not parts:
        return None

    label = None
    for part in parts:
        inferred_type = infer_annotation_type(label=part, note=part)
        if inferred_type != "note":
            label = part
            break

    note = " - ".join(parts)
    return ParsedVatbookAnnotation(
        row_number=row_number,
        label=label,
        note=note,
        annotation_type=infer_annotation_type(label=label, note=note),
        raw_cells=dict(cells),
    )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
