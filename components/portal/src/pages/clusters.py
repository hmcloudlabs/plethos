import re
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from auth import User, require_user
from config import config
from kube.vclusterclaim_service import VClusterClaimAlreadyExistsError, VClusterClaimService
from templating import templates

router = APIRouter()


def get_vcc_service() -> VClusterClaimService:
    return VClusterClaimService()


def _validate_new_cluster(name: str) -> str | None:
    """Return a user-facing error message, or None if the name is valid."""

    NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")

    if not name or len(name) > 63 or not NAME_RE.match(name):
        return "Name must be lowercase letters, digits and hyphens (max 63 chars)."
    
    return None


def _render_clusters(
    request: Request,
    user: User,
    vcc_service: VClusterClaimService,
    *,
    error: str | None = None,
    form_name: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "clusters.html",
        {
            "title": "My Clusters",
            "user": user,
            "claims": vcc_service.list_for_owner(user.sub),
            "error": error,
            "form_name": form_name,
        },
        status_code=status_code,
    )


@router.get("/clusters", response_class=HTMLResponse)
def clusters(
    request: Request,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimService = Depends(get_vcc_service),
) -> HTMLResponse:
    return _render_clusters(request, user, vcc_service)


@router.get("/clusters/list", response_class=HTMLResponse)
def clusters_list(
    request: Request,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimService = Depends(get_vcc_service),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "components/cluster_list.html",
        {"claims": vcc_service.list_for_owner(user.sub)},
    )


@router.post("/clusters")
def create_cluster(
    request: Request,
    name: str = Form(...),
    user: User = Depends(require_user),
    vcc_service: VClusterClaimService = Depends(get_vcc_service),
) -> Response:
    name = name.strip()

    error = _validate_new_cluster(name)
    if error is None:
        try:
            vcc_service.create(user.sub, user.email, name, config.latest_vcluster_version)
        except VClusterClaimAlreadyExistsError:
            error = f"You already have a cluster named '{name}'."

    if error is not None:
        return _render_clusters(request, user, vcc_service, error=error, form_name=name, status_code=400)

    return RedirectResponse("/clusters", status_code=303)
