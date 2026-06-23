import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    vcluster_version: str = "0.19.0"
    namespace: str = os.getenv("VCLUSTERCLAIMS_NAMESPACE", "vkube-system")


settings = Settings()
