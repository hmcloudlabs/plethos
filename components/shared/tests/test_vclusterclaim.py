from shared.vclusterclaim import (
    State,
    Phase,
    VClusterClaimSpec,
    VClusterClaimStatus,
)


def test_spec_parses_k8s_shaped_data():
    spec = VClusterClaimSpec.model_validate(
        {
            "name": "dev",
            "ownerSubject": "abc-123",
            "ownerEmail": "owner@hm.edu",
            "accessRules": [{"email": "u1@hm.edu"}],
        }
    )
    assert spec.name == "dev"
    assert spec.owner_email == "owner@hm.edu"
    assert spec.access_rules[0].email == "u1@hm.edu"
    # state defaults to Running
    assert spec.state is State.RUNNING


def test_status_phase():
    status = VClusterClaimStatus.model_validate({"phase": "Sleeping"})
    assert status.phase is Phase.SLEEPING
    assert status.model_dump(by_alias=True)["phase"] == "Sleeping"
