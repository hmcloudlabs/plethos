"""Routes for managing a user's VClusterClaims (list/create/sleep/wake/delete).

Currently a placeholder page; the k8s-backed listing and actions land in the
next increment (see services/claims.py).
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from auth import User, require_user
from templating import templates

router = APIRouter()


@router.get("/clusters", response_class=HTMLResponse)
async def clusters(request: Request, user: User = Depends(require_user)) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "clusters.html", {"title": "My Clusters", "user": user}
    )
