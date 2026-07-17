from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from auth import (
    NotAuthenticatedError,
    NotAuthorizedError,
    User,
    clear_session_user,
    set_session_user,
    sso_client,
)
from config import config
from kube.client import load_kube_config
from pages import admin, clusters, home
from templating import STATIC_DIR


@asynccontextmanager
async def lifespan(_app: FastAPI):
    load_kube_config()
    
    yield


app = FastAPI(title="vkube Portal", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=config.session_secret)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(home.router)
app.include_router(clusters.router)
app.include_router(admin.router)


@app.exception_handler(NotAuthenticatedError)
async def _redirect_to_login(request: Request, _exc: NotAuthenticatedError) -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)


@app.exception_handler(NotAuthorizedError)
async def _forbidden(request: Request, _exc: NotAuthorizedError) -> PlainTextResponse:
    return PlainTextResponse("Forbidden: admins only.", status_code=403)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


# SSO login/logout routes: the OIDC authorization-code round-trip.
@app.get("/login")
async def login(request: Request):
    redirect_uri = request.url_for("auth_callback")
    return await sso_client().authorize_redirect(request, str(redirect_uri))


@app.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request) -> RedirectResponse:
    client = sso_client()
    token = await client.authorize_access_token(request)
    claims = token.get("userinfo") or await client.userinfo(token=token)
    set_session_user(request, User.from_claims(dict(claims)))
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    clear_session_user(request)
    return RedirectResponse(url="/", status_code=303)
