import re
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from auth import User, require_user
from config import config
from kube.settings_service import SettingsService
from kube.vclusterclaim_model import VClusterClaim
from kube.vclusterclaim_repository import VClusterClaimAlreadyExistsError
from kube.vclusterclaim_service import (
    AccessType,
    VClusterClaimUserService,
)
from shared.vclusterclaim import State
from templating import templates
from utils import FlashLevel, is_valid_email, pop_flash, set_flash

router = APIRouter()


def get_vcc_service() -> VClusterClaimUserService:
    return VClusterClaimUserService()


def get_settings_service() -> SettingsService:
    return SettingsService()


def _owned_claim_or_404(
    vcc_service: VClusterClaimUserService, object_name: str, sub: str
) -> VClusterClaim:
    """Fetch a claim the user owns, or raise 404 (used by the owner-only access panel)."""

    claim = vcc_service.get_by_object_name(object_name)
    if claim is None or claim.access_for(sub) is not AccessType.OWNER:
        raise HTTPException(status_code=404, detail="Cluster not found.")
    return claim


def _validate_new_cluster(name: str) -> str | None:
    """Return a user-facing error message, or None if the name is valid."""

    NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
    if not name or len(name) > 63 or not NAME_RE.match(name):
        return "Name must be lowercase letters, digits and hyphens (max 63 chars)."

    return None


def _check_quota(
    vcc_service: VClusterClaimUserService, settings_service: SettingsService, sub: str
) -> str | None:
    """Return a user-facing error if the owner is already at their cluster quota, else None."""

    max_clusters = settings_service.max_clusters_per_user()
    if len(vcc_service.list_for_owner(sub)) >= max_clusters:
        return f"You've reached the maximum of {max_clusters} cluster(s) per user."

    return None


def _check_team_quota(
    claim: VClusterClaim, settings_service: SettingsService, member_email: str
) -> str | None:
    """Return a user-facing error if adding `member_email` would exceed the team-size quota, else None."""

    # Re-inviting an existing member doesn't grow the team, so it's exempt from the quota.
    if any(member.email == member_email for member in claim.spec.members):
        return None

    max_team_size = settings_service.max_team_size()
    if len(claim.spec.members) >= max_team_size:
        return f"This cluster already has the maximum of {max_team_size} shared member(s)."

    return None


def _render_clusters(
    request: Request,
    user: User,
    vcc_service: VClusterClaimUserService,
    *,
    flash: tuple[str, FlashLevel] | None = None,
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
            "flash_message": flash[0] if flash else None,
            "flash_level": flash[1] if flash else None,
            "form_name": form_name,
        },
        status_code=status_code,
    )


def _render_cluster_list(
    request: Request, user: User, vcc_service: VClusterClaimUserService
) -> HTMLResponse:
    """Self-refreshing table of the user's own clusters."""

    return templates.TemplateResponse(
        request,
        "components/cluster_list.html",
        {"vcluster_claims": vcc_service.list_for_owner(user.sub)},
    )


def _render_shared_cluster_list(
    request: Request, user: User, vcc_service: VClusterClaimUserService
) -> HTMLResponse:
    """Self-refreshing table of clusters shared with the user."""

    return templates.TemplateResponse(
        request,
        "components/shared_cluster_list.html",
        {"shared_vcluster_claims": vcc_service.list_shared_with(user.email)},
    )


def _render_after_action(
    request: Request, user: User, vcc_service: VClusterClaimUserService
) -> HTMLResponse:
    """Re-render whichever table triggered the action (owned vs shared).

    htmx sends the resolved target id in the HX-Target header; both tables only
    ever show the caller's own data, so this just picks the right fragment.
    """
    if request.headers.get("HX-Target") == "shared-cluster-list":
        return _render_shared_cluster_list(request, user, vcc_service)
    return _render_cluster_list(request, user, vcc_service)


def _render_access_panel(
    request: Request, claim: VClusterClaim, *, error: str | None = None
) -> HTMLResponse:
    """The manage-users modal body."""

    return templates.TemplateResponse(
        request,
        "components/access_panel.html",
        {
            "object_name": claim.object_name,
            "cluster_name": claim.spec.name,
            "members": claim.spec.members,
            "error": error,
        },
    )


@router.get("/clusters", response_class=HTMLResponse)
def clusters(
    request: Request,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimUserService = Depends(get_vcc_service),
) -> HTMLResponse:
    flash = pop_flash(request)
    form_name = request.session.pop("flash_form_name", "")
    return _render_clusters(request, user, vcc_service, flash=flash, form_name=form_name)


@router.get("/clusters/list", response_class=HTMLResponse)
def clusters_list(
    request: Request,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimUserService = Depends(get_vcc_service),
) -> HTMLResponse:
    return _render_cluster_list(request, user, vcc_service)


@router.get("/clusters/shared/list", response_class=HTMLResponse)
def shared_clusters_list(
    request: Request,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimUserService = Depends(get_vcc_service),
) -> HTMLResponse:
    return _render_shared_cluster_list(request, user, vcc_service)


@router.post("/clusters/{object_name}/sleep", response_class=HTMLResponse)
def sleep_cluster(
    object_name: str,
    request: Request,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimUserService = Depends(get_vcc_service),
) -> HTMLResponse:
    vcc_service.set_state(object_name, user.sub, user.email, State.SLEEPING)
    return _render_after_action(request, user, vcc_service)


@router.post("/clusters/{object_name}/wake", response_class=HTMLResponse)
def wake_cluster(
    object_name: str,
    request: Request,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimUserService = Depends(get_vcc_service),
) -> HTMLResponse:
    vcc_service.set_state(object_name, user.sub, user.email, State.RUNNING)
    return _render_after_action(request, user, vcc_service)


@router.post("/clusters/{object_name}/delete", response_class=HTMLResponse)
def delete_cluster(
    object_name: str,
    request: Request,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimUserService = Depends(get_vcc_service),
) -> HTMLResponse:
    vcc_service.delete(object_name, user.sub)
    return _render_cluster_list(request, user, vcc_service)


@router.get("/clusters/{object_name}/kubeconfig")
def download_kubeconfig(
    object_name: str,
    request: Request,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimUserService = Depends(get_vcc_service),
) -> Response:
    result = vcc_service.get_kubeconfig(object_name, user.sub, user.email)
    if result is None:
        set_flash(request, "Kubeconfig not available yet.", level="warning")
        return RedirectResponse("/clusters", status_code=303)

    display_name, kubeconfig = result
    return Response(
        content=kubeconfig,
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="{display_name}-kubeconfig.yaml"'},
    )


@router.get("/clusters/{object_name}/data")
def download_data(
    object_name: str,
    request: Request,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimUserService = Depends(get_vcc_service),
) -> Response:
    result = vcc_service.get_mounted_volume_contents(object_name, user.sub, user.email)
    if result is None:
        set_flash(request, "No data available to download.", level="warning")
        return RedirectResponse("/clusters", status_code=303)

    display_name, data = result
    return Response(
        content=data,
        media_type="application/x-tar",
        headers={"Content-Disposition": f'attachment; filename="{display_name}-data.tar"'},
    )


@router.get("/clusters/{object_name}/access", response_class=HTMLResponse)
def cluster_access(
    object_name: str,
    request: Request,
    user: User = Depends(require_user),
    vcc_service: VClusterClaimUserService = Depends(get_vcc_service),
) -> HTMLResponse:
    claim = _owned_claim_or_404(vcc_service, object_name, user.sub)
    return _render_access_panel(request, claim)


@router.post("/clusters/{object_name}/access", response_class=HTMLResponse)
def add_cluster_access(
    object_name: str,
    request: Request,
    email: str = Form(...),
    user: User = Depends(require_user),
    vcc_service: VClusterClaimUserService = Depends(get_vcc_service),
    settings_service: SettingsService = Depends(get_settings_service),
) -> HTMLResponse:
    claim = _owned_claim_or_404(vcc_service, object_name, user.sub)
    email = email.strip().lower()

    error: str | None = None
    if not is_valid_email(email):
        error = "Enter a valid email address."
    elif email == user.email.lower():
        error = "You can't add yourself."

    if error is None:
        error = _check_team_quota(claim, settings_service, email)

    if error is None:
        updated = vcc_service.add_access(object_name, user.sub, email)
        if updated is not None:
            claim = updated

    return _render_access_panel(request, claim, error=error)


@router.post("/clusters/{object_name}/access/remove", response_class=HTMLResponse)
def remove_cluster_access(
    object_name: str,
    request: Request,
    email: str = Form(...),
    user: User = Depends(require_user),
    vcc_service: VClusterClaimUserService = Depends(get_vcc_service),
) -> HTMLResponse:
    claim = vcc_service.remove_access(object_name, user.sub, email.strip().lower())

    if claim is None:
        raise HTTPException(status_code=404, detail="Cluster not found.")

    return _render_access_panel(request, claim)


@router.post("/clusters")
def create_cluster(
    request: Request,
    name: str = Form(...),
    user: User = Depends(require_user),
    vcc_service: VClusterClaimUserService = Depends(get_vcc_service),
    settings_service: SettingsService = Depends(get_settings_service),
) -> Response:
    name = name.strip()

    error = _validate_new_cluster(name)
    if error is None:
        error = _check_quota(vcc_service, settings_service, user.sub)

    if error is None:
        try:
            vcc_service.create(user.sub, user.email, name, config.latest_vcluster_version)
        except VClusterClaimAlreadyExistsError:
            error = f"You already have a cluster named '{name}'."

    if error is not None:
        set_flash(request, error)
        request.session["flash_form_name"] = name
    else:
        set_flash(request, f"Cluster '{name}' created.", level="success")

    return RedirectResponse("/clusters", status_code=303)
