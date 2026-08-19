import logging

from kube.settings_service import SettingsService
from kube.vclusterclaim_model import AccessType, VClusterClaim
from kube.vclusterclaim_repository import VClusterClaimRepository
from shared.vclusterclaim import Member, State, VClusterClaimSpec
from tokens import invite_tokens, keep_alive_tokens

logger = logging.getLogger(__name__)


class VClusterClaimUserService:
    """User-facing operations. Every method is scoped to what the caller (sub/email) may see or touch."""

    def __init__(self, repo: VClusterClaimRepository | None = None) -> None:
        self._repo = repo or VClusterClaimRepository()

    def list_for_owner(self, sub: str) -> list[VClusterClaim]:
        """List all VClusterClaims owned by a user given their subject id."""

        claims = self._repo.list_by_owner(sub)

        # The label-selector only embeds the sub's hash so re-check raw sub to avoid hash collisions
        return [claim for claim in claims if claim.spec.owner_subject == sub]

    def list_shared_with(self, email: str) -> list[VClusterClaim]:
        """Lists all clusters that a user's email was invited to (ie. written into `members`)."""

        email = email.lower()
        claims = self._repo.list_by_shared_member(email)

        # The label-selector only embeds the email's hash so re-check raw email to avoid hash collisions
        return [
            claim
            for claim in claims
            if claim.spec.owner_email.lower() != email
            and any(member.email.lower() == email for member in claim.spec.members)
        ]

    def get_by_object_name(self, object_name: str) -> VClusterClaim | None:
        """Fetch a VClusterClaim by its full object name. No authorization."""

        return self._repo.get(object_name)

    def create(self, sub: str, email: str, name: str, vcluster_version: str) -> VClusterClaim:
        spec = VClusterClaimSpec(
            name=name,
            owner_subject=sub,
            owner_email=email,
            v_cluster_version=vcluster_version,
        )
        claim = self._repo.create(sub, name, spec)
        logger.info(f"{email} created cluster '{name}' ({claim.object_name})")

        return claim

    def _get_for_owner(self, object_name: str, sub: str) -> VClusterClaim | None:
        """Load a claim if `sub` owns it, None if it doesn't exist or isn't theirs."""

        claim = self._repo.get(object_name)
        if claim is None or claim.access_for(sub) is not AccessType.OWNER:
            return None

        return claim

    def _get_for_member(self, object_name: str, sub: str, email: str = "") -> VClusterClaim | None:
        """Load a claim if `sub`/`email` is the owner or a shared member, None otherwise."""

        claim = self._repo.get(object_name)
        if claim is None or claim.access_for(sub, email) is None:
            return None

        return claim

    def set_state(self, object_name: str, sub: str, email: str, state: State) -> None:
        """Sleep/wake. Allowed for the owner or any shared member"""

        if self._get_for_member(object_name, sub, email) is None:
            return

        self._repo.patch_state(object_name, state)
        logger.info(f"{email} set cluster '{object_name}' to {state.value}")

    def renew(self, object_name: str, sub: str, email: str) -> None:
        """Keep-alive click from the portal UI. Allowed for the owner or any shared member."""

        if self._get_for_member(object_name, sub, email) is None:
            return

        self._repo.mark_renewed(object_name)
        logger.info(f"{email} renewed cluster '{object_name}'")


    def delete(self, object_name: str, sub: str) -> None:
        """Delete a cluster (owner only)."""

        if self._get_for_owner(object_name, sub) is None:
            return
        self._repo.delete(object_name)
        logger.info(f"Owner deleted cluster '{object_name}'")

    def invite_member(
        self, object_name: str, owner_sub: str, member_email: str
    ) -> tuple[VClusterClaim, str] | None:
        """Starts an invite (owner only): returns the claim and a signed accept token."""

        claim = self._get_for_owner(object_name, owner_sub)
        if claim is None:
            return None

        logger.info(f"Invite created for {member_email} to cluster '{object_name}'")
        return claim, invite_tokens.generate({"object_name": object_name, "email": member_email})

    def accept_invite(self, token: str, settings_service: SettingsService) -> VClusterClaim | None:
        """
        Grants access to a cluster from a signed invite token.

        Returns None if the token is invalid/expired, the cluster is gone or the
        team-size quota has since been reached.
        """

        payload = invite_tokens.verify(token)
        if payload is None:
            return None

        object_name, member_email = payload["object_name"], payload["email"]
        claim = self._repo.get(object_name)
        if claim is None:
            return None

        if any(member.email == member_email for member in claim.spec.members):
            return claim  # already a member, nothing to do

        if len(claim.spec.members) >= settings_service.max_team_size(claim.spec.owner_email):
            logger.warning(f"{member_email} could not join '{object_name}': team-size quota reached")
            return None

        members = [*claim.spec.members, Member(email=member_email)]
        claim = self._repo.add_member(object_name, members, member_email)
        logger.info(f"{member_email} accepted invite to cluster '{object_name}'")

        return claim

    def remove_member(
        self, object_name: str, owner_sub: str, member_email: str
    ) -> VClusterClaim | None:
        """Revoke a member's access (owner only), returns None if not found/owned."""

        claim = self._get_for_owner(object_name, owner_sub)
        if claim is None:
            return None

        members = [member for member in claim.spec.members if member.email != member_email]

        claim = self._repo.remove_member(object_name, members, member_email)
        logger.info(f"Removed {member_email} from cluster '{object_name}'")

        return claim

    def get_kubeconfig(self, object_name: str, sub: str, email: str) -> tuple[str, str] | None:
        """Returns the VClusterClaim name and its vCluster kubeconfig for the owner or shared member."""

        claim = self._get_for_member(object_name, sub, email)
        if claim is None:
            return None

        kubeconfig = self._repo.read_kubeconfig(object_name)
        if kubeconfig is None:
            return None

        return claim.spec.name, kubeconfig

    def get_mounted_volume_contents(
        self, object_name: str, sub: str, email: str
    ) -> tuple[str, bytes] | None:
        """
        Returns the VClusterClaim name and a tar archive of the data in 
        its workload pods PVC volumes, for the owner or a shared member.
        """

        claim = self._get_for_member(object_name, sub, email)
        if claim is None:
            return None

        data = self._repo.read_mounted_volume_contents(object_name)
        if data is None:
            return None

        return claim.spec.name, data
        
    def confirm_keep_alive(self, token: str) -> VClusterClaim | None:
        """
        Renews a cluster from a signed keep-alive token (sent by the inactivity job's warning
        emails), clearing any pending warnings.

        Returns None if the token is invalid/expired or the cluster is gone.
        """

        payload = keep_alive_tokens.verify(token)
        if payload is None:
            return None

        object_name = payload["object_name"]
        claim = self._repo.get(object_name)
        if claim is None:
            return None

        self._repo.mark_renewed(object_name)

        logger.info(f"Cluster '{object_name}' renewed via keep-alive link")

        return claim


class VClusterClaimAdminService:
    def __init__(self, repo: VClusterClaimRepository | None = None) -> None:
        self._repo = repo or VClusterClaimRepository()

    def list_all(self) -> list[VClusterClaim]:
        """Every VClusterClaim across all users."""
        return self._repo.list_all()

    def get_by_object_name(self, object_name: str) -> VClusterClaim | None:
        return self._repo.get(object_name)

    def get_logs(self, object_name: str, tail_lines: int = 200) -> str | None:
        """Logs of the vcluster control-plane pod, or None if it isn't up yet."""
        return self._repo.read_control_plane_logs(object_name, tail_lines)

    def set_state(self, object_name: str, state: State) -> None:
        """Sleep/wake any cluster, regardless of ownership."""
        self._repo.patch_state(object_name, state)
        logger.info(f"Admin set cluster '{object_name}' to {state.value}")

    def delete(self, object_name: str) -> None:
        """Delete any cluster, regardless of ownership."""
        self._repo.delete(object_name)
        logger.info(f"Admin deleted cluster '{object_name}'")

    def delete_all_for_owner(self, owner_email: str) -> int:
        """Delete every cluster owned by the given email. Returns the count deleted."""

        owner_email = owner_email.lower()
        owned = [
            claim
            for claim in self._repo.list_all()
            if claim.spec.owner_email.lower() == owner_email
        ]
        for claim in owned:
            self._repo.delete(claim.object_name)

        logger.info(f"Admin deleted all {len(owned)} cluster(s) owned by {owner_email}")
        return len(owned)

    def get_kubeconfig(self, object_name: str) -> tuple[str, str] | None:
        """Returns the VClusterClaim name and its vCluster kubeconfig"""

        claim = self._repo.get(object_name)
        if claim is None:
            return None

        kubeconfig = self._repo.read_kubeconfig(object_name)
        if kubeconfig is None:
            return None

        return claim.spec.name, kubeconfig

