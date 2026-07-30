from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from auth import User, require_admin
from kube.settings_service import SettingsService
from kube.vclusterclaim_model import VClusterClaim
from kube.vclusterclaim_service import VClusterClaimAdminService
from shared.vclusterclaim import State
from templating import templates
from utils import is_valid_email

router = APIRouter()


def get_vcc_admin_service() -> VClusterClaimAdminService:
    return VClusterClaimAdminService()


def get_settings_service() -> SettingsService:
    return SettingsService()


def _derive_owners(vcc_claims: list[VClusterClaim]) -> list[dict]:
    """We have no user store, so an "owner" is anyone who owns at least one cluster."""

    counts: dict[str, int] = {}
    for vcc_claim in vcc_claims:
        counts[vcc_claim.spec.owner_email] = counts.get(vcc_claim.spec.owner_email, 0) + 1

    return [{"email": email, "clusters": n} for email, n in sorted(counts.items())]


def _render_admin_cluster_list(
    request: Request, vcc_service: VClusterClaimAdminService
) -> HTMLResponse:
    """Self-refreshing table of every cluster (admin)."""

    return templates.TemplateResponse(
        request,
        "components/admin_cluster_list.html",
        {"vcluster_claims": vcc_service.list_all()},
    )


def _render_admin_owner_list(
    request: Request, vcc_service: VClusterClaimAdminService
) -> HTMLResponse:
    """The owners table (derived from cluster ownership)."""

    return templates.TemplateResponse(
        request,
        "components/admin_owner_list.html",
        {"owners": _derive_owners(vcc_service.list_all())},
    )


def _render_admin_settings(
    request: Request,
    user: User,
    settings_service: SettingsService,
    *,
    error: str | None = None,
    success: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "components/admin_settings.html",
        {
            "user": user,
            "admin_emails": settings_service.list_admins(),
            "max_clusters_per_user": settings_service.max_clusters_per_user(),
            "max_team_size": settings_service.max_team_size(),
            "error": error,
            "success": success,
        },
    )


@router.get("/admin", response_class=HTMLResponse)
def admin(
    request: Request,
    user: User = Depends(require_admin),
    vcc_service: VClusterClaimAdminService = Depends(get_vcc_admin_service),
    settings_service: SettingsService = Depends(get_settings_service),
) -> HTMLResponse:
    vcc_claims = vcc_service.list_all()
    owners = _derive_owners(vcc_claims)
    stats = {
        "owners": len(owners),
        "clusters": len(vcc_claims),
        "running": sum(1 for vcc_claim in vcc_claims if vcc_claim.status.phase == "Ready"),
    }
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "title": "Admin",
            "user": user,
            "vcluster_claims": vcc_claims,
            "owners": owners,
            "stats": stats,
            "admin_emails": settings_service.list_admins(),
            "max_clusters_per_user": settings_service.max_clusters_per_user(),
            "max_team_size": settings_service.max_team_size(),
        },
    )


@router.get("/admin/clusters/list", response_class=HTMLResponse)
def admin_cluster_list(
    request: Request,
    user: User = Depends(require_admin),
    vcc_service: VClusterClaimAdminService = Depends(get_vcc_admin_service),
) -> HTMLResponse:
    return _render_admin_cluster_list(request, vcc_service)


@router.get("/admin/clusters/{object_name}/logs", response_class=HTMLResponse)
def admin_cluster_logs(
    object_name: str,
    request: Request,
    user: User = Depends(require_admin),
    vcc_service: VClusterClaimAdminService = Depends(get_vcc_admin_service),
) -> HTMLResponse:
    vcc_claim = vcc_service.get_by_object_name(object_name)
    logs = vcc_service.get_logs(object_name)

    return templates.TemplateResponse(
        request,
        "components/admin_logs_panel.html",
        {
            "object_name": object_name,
            "cluster_name": vcc_claim.spec.name if vcc_claim else object_name,
            "logs": logs,
        },
    )


@router.post("/admin/clusters/{object_name}/sleep", response_class=HTMLResponse)
def admin_sleep_cluster(
    object_name: str,
    request: Request,
    user: User = Depends(require_admin),
    vcc_service: VClusterClaimAdminService = Depends(get_vcc_admin_service),
) -> HTMLResponse:
    vcc_service.set_state(object_name, State.SLEEPING)
    return _render_admin_cluster_list(request, vcc_service)


@router.post("/admin/clusters/{object_name}/wake", response_class=HTMLResponse)
def admin_wake_cluster(
    object_name: str,
    request: Request,
    user: User = Depends(require_admin),
    vcc_service: VClusterClaimAdminService = Depends(get_vcc_admin_service),
) -> HTMLResponse:
    vcc_service.set_state(object_name, State.RUNNING)
    return _render_admin_cluster_list(request, vcc_service)


@router.post("/admin/clusters/{object_name}/delete", response_class=HTMLResponse)
def admin_delete_cluster(
    object_name: str,
    request: Request,
    user: User = Depends(require_admin),
    vcc_service: VClusterClaimAdminService = Depends(get_vcc_admin_service),
) -> HTMLResponse:
    vcc_service.delete(object_name)
    return _render_admin_cluster_list(request, vcc_service)


@router.post("/admin/owners/delete", response_class=HTMLResponse)
def admin_delete_owner(
    request: Request,
    email: str = Form(...),
    user: User = Depends(require_admin),
    vcc_service: VClusterClaimAdminService = Depends(get_vcc_admin_service),
) -> HTMLResponse:
    vcc_service.delete_all_for_owner(email.strip().lower())
    return _render_admin_owner_list(request, vcc_service)


@router.post("/admin/settings/max-clusters", response_class=HTMLResponse)
def admin_set_max_clusters(
    request: Request,
    max_clusters_per_user: int = Form(...),
    user: User = Depends(require_admin),
    settings_service: SettingsService = Depends(get_settings_service),
) -> HTMLResponse:
    error: str | None = None
    success: str | None = None
    if max_clusters_per_user < 1:
        error = "Max clusters per user must be at least 1."
    else:
        settings_service.set_max_clusters_per_user(max_clusters_per_user)
        success = f"Max clusters per user set to {max_clusters_per_user}."

    return _render_admin_settings(request, user, settings_service, error=error, success=success)


@router.post("/admin/settings/max-team-size", response_class=HTMLResponse)
def admin_set_max_team_size(
    request: Request,
    max_team_size: int = Form(...),
    user: User = Depends(require_admin),
    settings_service: SettingsService = Depends(get_settings_service),
) -> HTMLResponse:
    error: str | None = None
    success: str | None = None
    if max_team_size < 1:
        error = "Max team size must be at least 1."
    else:
        settings_service.set_max_team_size(max_team_size)
        success = f"Max team size set to {max_team_size}."

    return _render_admin_settings(request, user, settings_service, error=error, success=success)


@router.post("/admin/settings/admins/add")
def admin_add_admin(
    request: Request,
    email: str = Form(...),
    user: User = Depends(require_admin),
    settings_service: SettingsService = Depends(get_settings_service),
) -> HTMLResponse:
    email = email.strip().lower()

    error: str | None = None
    if not is_valid_email(email):
        error = "Enter a valid email address."
    elif email == user.email.lower():
        error = "You can't add yourself."

    if error is None:
        settings_service.add_admin(email)

    return _render_admin_settings(request, user, settings_service, error=error)


@router.post("/admin/settings/admins/remove", response_class=HTMLResponse)
def admin_remove_admin(
    request: Request,
    email: str = Form(...),
    user: User = Depends(require_admin),
    settings_service: SettingsService = Depends(get_settings_service),
) -> HTMLResponse:
    email = email.strip().lower()

    error: str | None = None
    if not is_valid_email(email):
        error = "Enter a valid email address."
    elif email == user.email.lower():
        error = "You can't remove yourself."

    if error:
        return _render_admin_settings(
            request, user, settings_service, error=error
        )

    settings_service.remove_admin(email)
    return _render_admin_settings(request, user, settings_service)
