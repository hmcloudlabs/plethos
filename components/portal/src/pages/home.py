from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from auth import get_session_user
from kube.vclusterclaim_service import VClusterClaimUserService
from templating import templates

router = APIRouter()


# Sync: may query Kubernetes (blocking) for the signed-in user's usage summary.
@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    user = get_session_user(request)

    cluster_summary = None
    if user is not None:
        service = VClusterClaimUserService()
        claims = service.list_for_owner(user.sub)
        cluster_summary = {
            "total": len(claims),
            "running": sum(1 for c in claims if c.status.phase == "Running"),
            "shared": len(service.list_shared_with(user.email)),
        }

    return templates.TemplateResponse(
        request,
        "index.html",
        {"title": "Plethos", "user": user, "cluster_summary": cluster_summary},
    )
