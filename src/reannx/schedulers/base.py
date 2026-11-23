from __future__ import annotations

from enum import Enum

from ..config import Cluster, JobSpec, Resources


class State(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"

    @property
    def terminal(self) -> bool:
        return self in (State.COMPLETED, State.FAILED, State.CANCELLED, State.TIMEOUT)


class Scheduler:
    name = "base"
    prefix = ""

    def directives(self, spec: JobSpec, res: Resources, cluster: Cluster, run_dir: str) -> list[str]:
        raise NotImplementedError

    def submit_cmd(self, run_dir: str) -> str:
        raise NotImplementedError

    def parse_job_id(self, out: str) -> str:
        raise NotImplementedError

    def status_cmd(self, job_id: str) -> str:
        raise NotImplementedError

    def parse_status(self, out: str) -> tuple[State, dict]:
        raise NotImplementedError

    def cancel_cmd(self, job_id: str) -> str:
        raise NotImplementedError

    def extra(self, cluster: Cluster) -> list[str]:
        """Raw extra directives from the cluster profile ([defaults] extra_directives)."""
        return [f"{self.prefix} {d}" for d in cluster.defaults.get("extra_directives", [])]
