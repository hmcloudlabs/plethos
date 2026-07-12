from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from auth import (
    NotAuthenticatedError,
    User,
    clear_user,
    get_current_user,
    require_user,
    save_user,
    sso_client,
)
from config import config

_BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))

app = FastAPI(title="vkube Portal")
app.add_middleware(SessionMiddleware, secret_key=config.session_secret)
app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")


@app.exception_handler(NotAuthenticatedError)
async def _redirect_to_login(request: Request, _exc: NotAuthenticatedError) -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/login")
async def login(request: Request):
    redirect_uri = request.url_for("auth_callback")
    return await sso_client().authorize_redirect(request, str(redirect_uri))


@app.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request) -> RedirectResponse:
    client = sso_client()
    token = await client.authorize_access_token(request)
    claims = token.get("userinfo") or await client.userinfo(token=token)
    save_user(request, User.from_claims(dict(claims)))
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    clear_user(request)
    return RedirectResponse(url="/", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    user = get_current_user(request)
    return templates.TemplateResponse(
        request, "index.html", {"title": "vkube Portal", "user": user}
    )


@app.get("/clusters", response_class=HTMLResponse)
async def clusters(request: Request, user: User = Depends(require_user)) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "clusters.html", {"title": "My Clusters", "user": user}
    )
