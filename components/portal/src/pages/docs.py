import markdown
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from auth import get_session_user
from templating import DOCS_DIR, templates

router = APIRouter()


@router.get("/docs", response_class=HTMLResponse)
def show_docs(request: Request) -> HTMLResponse:
    source = (DOCS_DIR / "guide.md").read_text()
    body = markdown.markdown(source, extensions=["fenced_code", "tables"])

    return templates.TemplateResponse(
        request,
        "docs.html",
        {"title": "Docs", "user": get_session_user(request), "body": body},
    )
