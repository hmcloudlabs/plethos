from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

GROUP = "vkube.cs.hm.edu"
VERSION = "v1alpha1"
KIND = "VClusterClaim"
PLURAL = "vclusterclaims"


class DesiredState(StrEnum):
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


class _Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Subject(_Model):
    sub: str
    email: str


class AccessRule(_Model):
    subject: Subject
    role: Literal["admin", "viewer"]


class VClusterClaimSpec(_Model):
    name: str
    owner_sub: str
    owner_email: str
    desired_state: DesiredState = DesiredState.RUNNING
    access_rules: list[AccessRule] = Field(default_factory=list)


class VClusterClaimStatus(_Model):
    phase: Phase | None = None
    message: str | None = None
    observed_generation: int | None = None
