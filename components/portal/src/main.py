import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from auth import (
    NotAuthenticatedError,
    NotAuthorizedError,
    User,
    clear_session_user,
    get_session_user,
    set_session_user,
    sso_client,
)
from config import config
from kube.client import load_kube_config
from logging_setup import setup_logging
from pages import admin, clusters, guides, home
from templating import STATIC_DIR

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Starting vkube portal")
    load_kube_config()

    yield

    logger.info("Shutting down vkube portal")


app = FastAPI(title="vkube Portal", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=config.session_secret)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(home.router)
app.include_router(clusters.router)
app.include_router(admin.router)
app.include_router(guides.router)


@app.middleware("http")
async def log_requests(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Custom logging that replaces uvicorns access logs, so they fit"""

    try:
        response = await call_next(request)
    except Exception:
        logger.exception(f'"{request.method} {request.url.path}" unhandled exception')
        raise

    if request.method != "GET" or not (200 <= response.status_code < 300):
        client = request.client.host if request.client else "-"
        logger.info(f'{client} "{request.method} {request.url.path}" {response.status_code}')

    return response


@app.exception_handler(NotAuthenticatedError)
async def _redirect_to_login(request: Request, _exc: NotAuthenticatedError) -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)


@app.exception_handler(NotAuthorizedError)
async def _forbidden(request: Request, _exc: NotAuthorizedError) -> PlainTextResponse:
    logger.warning(f"Forbidden: non-admin tried to access {request.url.path}")
    return PlainTextResponse("Forbidden: admins only.", status_code=403)


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

    user = User.from_claims(dict(claims))
    set_session_user(request, user)
    logger.info(f"User logged in: {user.email}")

    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    user = get_session_user(request)
    if user is not None:
        logger.info(f"User logged out: {user.email}")

    clear_session_user(request)
    return RedirectResponse(url="/", status_code=303)
