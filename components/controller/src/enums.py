from enum import StrEnum


class JobStatus(StrEnum):
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
