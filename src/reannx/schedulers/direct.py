from __future__ import annotations

from .base import Scheduler, State


class Direct(Scheduler):
    """No scheduler: the script runs synchronously on the login node over ssh.
    Final state comes from the exit_code sentinel file written by job.sh."""
    name = "direct"

    def directives(self, spec, res, cluster, run_dir):
        return []

    def submit_cmd(self, run_dir):
        return f"cd {run_dir} && bash job.sh > stdout.log 2> stderr.log"

    def parse_job_id(self, out):
        return "direct"

    def status_cmd(self, job_id):
        return "true"

    def parse_status(self, out):
        return State.UNKNOWN, {}

    def cancel_cmd(self, job_id):
        return "true"
