from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


router = APIRouter(include_in_schema=False)

REVIEW_UI_PATH = Path(__file__).resolve().parents[1] / "static" / "reconciliation-review.html"


@router.get("/review")
async def get_reconciliation_review_page():
    return FileResponse(REVIEW_UI_PATH)
