import re
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from auth import User, require_user
from config import config
from kube.vclusterclaim_model import VClusterClaim
from kube.vclusterclaim_service import VClusterClaimAlreadyExistsError, VClusterClaimService
from shared.vclusterclaim import State
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
            "title": "Clusters",
            "user": user,
            "vcluster_claims": vcc_service.list_for_owner(user.sub),
            "shared_vcluster_claims": vcc_service.list_shared_with(user.email),
            "error": error,
            "form_name": form_name,
        },
        status_code=status_code,
    )


def _render_cluster_list(
    request: Request, user: User, vcc_service: VClusterClaimService
) -> HTMLResponse:
    """Self-refreshing cluster table."""

    return templates.TemplateResponse(
        request,
        "components/cluster_list.html",
        {"vcluster_claims": vcc_service.list_for_owner(user.sub)},
    )


def _render_access_panel(
    request: Request, name: str, claim: VClusterClaim, *, error: str | None = None
) -> HTMLResponse:
    """The manage-users modal body."""

    return templates.TemplateResponse(
        request,
        "components/access_panel.html",
        {"cluster_name": name, "access_rules": claim.spec.access_rules, "error": error},
    )


@router.get("/clusters", response_class=HTMLResponse)
def clusters(
    request: Request,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimService = Depends(get_vcc_service),
) -> HTMLResponse:
    error = request.session.pop("flash_error", None)
    form_name = request.session.pop("flash_form_name", "")
    return _render_clusters(request, user, vcc_service, error=error, form_name=form_name)



@router.get("/clusters/list", response_class=HTMLResponse)
def clusters_list(
    request: Request,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimService = Depends(get_vcc_service),
) -> HTMLResponse:
    return _render_cluster_list(request, user, vcc_service)


@router.post("/clusters/{name}/sleep", response_class=HTMLResponse)
def sleep_cluster(
    name: str,
    request: Request,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimService = Depends(get_vcc_service),
) -> HTMLResponse:
    vcc_service.set_state(user.sub, name, State.SLEEPING)
    return _render_cluster_list(request, user, vcc_service)


@router.post("/clusters/{name}/wake", response_class=HTMLResponse)
def wake_cluster(
    name: str,
    request: Request,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimService = Depends(get_vcc_service),
) -> HTMLResponse:
    vcc_service.set_state(user.sub, name, State.RUNNING)
    return _render_cluster_list(request, user, vcc_service)


@router.post("/clusters/{name}/delete", response_class=HTMLResponse)
def delete_cluster(
    name: str,
    request: Request,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimService = Depends(get_vcc_service),
) -> HTMLResponse:
    vcc_service.delete(user.sub, name)
    return _render_cluster_list(request, user, vcc_service)


@router.get("/clusters/{name}/kubeconfig")
def download_kubeconfig(
    name: str,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimService = Depends(get_vcc_service),
) -> Response:
    kubeconfig = vcc_service.get_kubeconfig(user.sub, name)
    if kubeconfig is None:
        raise HTTPException(status_code=404, detail="Kubeconfig not available yet.")

    return Response(
        content=kubeconfig,
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="{name}-kubeconfig.yaml"'},
    )


@router.get("/clusters/{name}/access", response_class=HTMLResponse)
def cluster_access(
    name: str,
    request: Request,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimService = Depends(get_vcc_service),
) -> HTMLResponse:
    claim = vcc_service.get(user.sub, name)
    if claim is None:
        raise HTTPException(status_code=404, detail="Cluster not found.")
    return _render_access_panel(request, name, claim)


@router.post("/clusters/{name}/access", response_class=HTMLResponse)
def add_cluster_access(
    name: str,
    request: Request,
    email: str = Form(...),
    user: User = Depends(require_user),
    vcc_service: VClusterClaimService = Depends(get_vcc_service),
) -> HTMLResponse:
    email = email.strip().lower()

    EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    error: str | None = None
    if not EMAIL_RE.match(email):
        error = "Enter a valid email address."
    elif email == user.email.lower():
        error = "You can't add yourself."

    if error is None:
        claim = vcc_service.add_access(user.sub, name, email)
    else:
        claim = vcc_service.get(user.sub, name)

    if claim is None:
        raise HTTPException(status_code=404, detail="Cluster not found.")
    
    return _render_access_panel(request, name, claim, error=error)


@router.post("/clusters/{name}/access/remove", response_class=HTMLResponse)
def remove_cluster_access(
    name: str,
    request: Request,
    email: str = Form(...),
    user: User = Depends(require_user),
    vcc_service: VClusterClaimService = Depends(get_vcc_service),
) -> HTMLResponse:
    claim = vcc_service.remove_access(user.sub, name, email.strip().lower())

    if claim is None:
        raise HTTPException(status_code=404, detail="Cluster not found.")
    
    return _render_access_panel(request, name, claim)


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
        request.session["flash_error"] = error
        request.session["flash_form_name"] = name

    return RedirectResponse("/clusters", status_code=303)
