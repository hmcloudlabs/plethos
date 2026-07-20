from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from auth import User, require_admin
from kube.vclusterclaim_model import VClusterClaim
from kube.vclusterclaim_service import VClusterClaimAdminService
from shared.vclusterclaim import State
from templating import templates

router = APIRouter()


def get_vcc_admin_service() -> VClusterClaimAdminService:
    return VClusterClaimAdminService()


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


@router.get("/admin", response_class=HTMLResponse)
def admin(
    request: Request,
    user: User = Depends(require_admin),
    vcc_service: VClusterClaimAdminService = Depends(get_vcc_admin_service),
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
