from kube.vclusterclaim_model import AccessType, VClusterClaim
from kube.vclusterclaim_repository import (
    VClusterClaimRepository,
    owner_subject_hash,
    vcc_name,
)
from shared.vclusterclaim import AccessRule, State, VClusterClaimSpec


class VClusterClaimUserService:
    """User-facing operations. Every method is scoped to what the caller (sub/email) may see or touch."""

    def __init__(self, repo: VClusterClaimRepository | None = None) -> None:
        self._repo = repo or VClusterClaimRepository()

    def list_for_owner(self, sub: str) -> list[VClusterClaim]:
        """List all VClusterClaims owned by a user given their subject id."""

        claims = self._repo.list_by_owner_hash(owner_subject_hash(sub))

        # The label-selector only embeds the sub's hash so re-check raw sub to avoid hash collisions
        return [claim for claim in claims if claim.spec.owner_subject == sub]

    def list_shared_with(self, email: str) -> list[VClusterClaim]:
        """Lists all clusters that a user's email was invited to (ie. written into the `accessRules`).

        Access is keyed by email, which no label indexes, so we list every VClusterClaim in the (single)
        namespace and filter in memory. This is fine for now (as long as the amount of clusters stay in small scale).
        """

        email = email.lower()
        return [
            claim
            for claim in self._repo.list_all()
            if claim.spec.owner_email.lower() != email
            and any(rule.email.lower() == email for rule in claim.spec.access_rules)
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
        return self._repo.create(vcc_name(sub, name), owner_subject_hash(sub), spec)
    
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

    def delete(self, object_name: str, sub: str) -> None:
        """Delete a cluster (owner only)."""

        if self._get_for_owner(object_name, sub) is None:
            return
        self._repo.delete(object_name)

    def add_access(self, object_name: str, owner_sub: str, member_email: str) -> VClusterClaim | None:
        """Grants a member access (owner only), returns None if not found/owned."""

        claim = self._get_for_owner(object_name, owner_sub)
        if claim is None:
            return None

        # Drop any existing rule for this email in the current VClusterClaim before re-adding.
        rules = [rule for rule in claim.spec.access_rules if rule.email != member_email]
        rules.append(AccessRule(email=member_email))

        return self._repo.patch_access_rules(object_name, rules)

    def remove_access(self, object_name: str, owner_sub: str, member_email: str) -> VClusterClaim | None:
        """Revoke a member's access. Owner only; returns None if not found/not owned."""

        claim = self._get_for_owner(object_name, owner_sub)
        if claim is None:
            return None

        rules = [rule for rule in claim.spec.access_rules if rule.email != member_email]

        return self._repo.patch_access_rules(object_name, rules)

    def get_kubeconfig(self, object_name: str, sub: str, email: str) -> tuple[str, str] | None:
        """Returns the VClusterClaim name and its vCluster kubeconfig for the owner or shared member."""

        claim = self._get_for_member(object_name, sub, email)
        if claim is None:
            return None

        kubeconfig = self._repo.read_kubeconfig(object_name)
        if kubeconfig is None:
            return None

        return claim.spec.name, kubeconfig
    


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
 
    def delete(self, object_name: str) -> None:
        """Delete any cluster, regardless of ownership."""
        self._repo.delete(object_name)
 
    def delete_all_for_owner(self, owner_email: str) -> int:
        """Delete every cluster owned by the given email. Returns the count deleted."""

        owner_email = owner_email.lower()
        owned = [claim for claim in self._repo.list_all() if claim.spec.owner_email.lower() == owner_email]
        for claim in owned:
            self._repo.delete(claim.object_name)
 
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
 