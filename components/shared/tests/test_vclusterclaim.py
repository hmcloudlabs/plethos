from shared.vclusterclaim import (
    DesiredState,
    Phase,
    VClusterClaimSpec,
    VClusterClaimStatus,
)


def test_spec_parses_k8s_shaped_data():
    spec = VClusterClaimSpec.model_validate(
        {
            "name": "dev",
            "ownerSub": "abc-123",
            "ownerEmail": "owner@hm.edu",
            "accessRules": [{"subject": {"sub": "u-1", "email": "u1@hm.edu"}, "role": "admin"}],
        }
    )
    assert spec.name == "dev"
    assert spec.owner_email == "owner@hm.edu"
    assert spec.access_rules[0].subject.email == "u1@hm.edu"
    assert spec.access_rules[0].role == "admin"
    # desiredState defaults to Running
    assert spec.desired_state is DesiredState.RUNNING


def test_status_phase():
    status = VClusterClaimStatus.model_validate({"phase": "Sleeping"})
    assert status.phase is Phase.SLEEPING
    assert status.model_dump(by_alias=True)["phase"] == "Sleeping"
