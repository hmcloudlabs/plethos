import markdown
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from auth import get_session_user
from templating import templates

router = APIRouter()


@router.get("/guides", response_class=HTMLResponse)
def show_docs(request: Request) -> HTMLResponse:
    rendered = templates.get_template("guides.md").render()
    body = markdown.markdown(rendered, extensions=["fenced_code", "tables", "toc"])

    return templates.TemplateResponse(
        request,
        "docs.html",
        {"title": "Guides", "user": get_session_user(request), "body": body},
    )
