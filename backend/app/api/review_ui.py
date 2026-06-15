from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


router = APIRouter(include_in_schema=False)

REVIEW_UI_PATH = Path(__file__).resolve().parents[1] / "static" / "reconciliation-review.html"
SUPPLIER_DOCUMENTS_UI_PATH = Path(__file__).resolve().parents[1] / "static" / "supplier-documents.html"
STATEMENT_WORKBENCH_UI_PATH = Path(__file__).resolve().parents[1] / "static" / "statement-workbench.html"
MONTH_AUDIT_UI_PATH = Path(__file__).resolve().parents[1] / "static" / "month-audit.html"
TRANSACTIONS_UI_PATH = Path(__file__).resolve().parents[1] / "static" / "transactions.html"
VAT_BOOK_UI_PATH = Path(__file__).resolve().parents[1] / "static" / "vat-book.html"


@router.get("/review")
async def get_reconciliation_review_page():
    return FileResponse(REVIEW_UI_PATH)


@router.get("/supplier-documents")
async def get_supplier_documents_page():
    return FileResponse(SUPPLIER_DOCUMENTS_UI_PATH)


@router.get("/statement-workbench")
async def get_statement_workbench_page():
    return FileResponse(STATEMENT_WORKBENCH_UI_PATH)


@router.get("/month-audit")
async def get_month_audit_page():
    return FileResponse(MONTH_AUDIT_UI_PATH)


@router.get("/transactions")
async def get_transactions_page():
    return FileResponse(TRANSACTIONS_UI_PATH)


@router.get("/vat-book")
async def get_vat_book_page():
    return FileResponse(VAT_BOOK_UI_PATH)
