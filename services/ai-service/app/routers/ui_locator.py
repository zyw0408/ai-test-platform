from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .deps import get_current_user, get_ui_locator
from app.models import UiLocatorInspectRequest, UiLocatorInspectResponse

router = APIRouter(prefix="/ui-locator", tags=["ui-locator"])


@router.post("/inspect", response_model=UiLocatorInspectResponse)
async def inspect_ui_elements(
    payload: UiLocatorInspectRequest,
    _: dict = Depends(get_current_user),
    ui_locator = Depends(get_ui_locator),
) -> UiLocatorInspectResponse:
    try:
        result = ui_locator.inspect(payload)
        return UiLocatorInspectResponse.model_validate(result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/interactive-inspect")
async def interactive_inspect_ui_elements(
    payload: UiLocatorInspectRequest,
    _: dict = Depends(get_current_user),
    ui_locator = Depends(get_ui_locator),
):
    try:
        return ui_locator.interactive_inspect(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
