"""The public landing / home page (no login required)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from auth import get_session_user
from templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    user = get_session_user(request)
    return templates.TemplateResponse(
        request, "index.html", {"title": "vkube Portal", "user": user}
    )
