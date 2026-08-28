from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

GROUP = "plethos.cs.hm.edu"
VERSION = "v1alpha1"
KIND = "VClusterClaim"
PLURAL = "vclusterclaims"


class State(StrEnum):
    RUNNING = "Running"
    SLEEPING = "Sleeping"


class Phase(StrEnum):
    PENDING = "Pending"
    PROVISIONING = "Provisioning"
    READY = "Ready"
    SLEEPING = "Sleeping"
    WAKING = "Waking"
    ERROR = "Error"
    DELETING = "Deleting"


class ConditionType(StrEnum):
    READY = "Ready"


class _Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Member(_Model):
    email: str


class VClusterClaimSpec(_Model):
    name: str
    owner_subject: str
    owner_email: str
    v_cluster_version: str = "0.35.0"
    state: State = State.RUNNING
    members: list[Member] = Field(default_factory=list)


class Condition(_Model):
    type: str
    status: Literal["True", "False", "Unknown"]
    reason: str
    message: str
    last_transition_time: str
    observed_generation: int | None = None


class VClusterClaimStatus(_Model):
    phase: Phase | None = None
    message: str | None = None
    observed_generation: int | None = None
    conditions: list[Condition] = Field(default_factory=list)

    def has_condition(self, cond_type: ConditionType, status: str = "True") -> bool:
        return any(c.type == cond_type and c.status == status for c in self.conditions)
