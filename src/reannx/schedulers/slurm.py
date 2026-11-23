from __future__ import annotations

import re

from ..config import parse_mem_mb, parse_walltime
from .base import Scheduler, State

_MAP = {"PENDING": State.PENDING, "CONFIGURING": State.PENDING, "REQUEUED": State.PENDING,
        "RUNNING": State.RUNNING, "COMPLETING": State.RUNNING, "SUSPENDED": State.RUNNING,
        "COMPLETED": State.COMPLETED, "FAILED": State.FAILED, "NODE_FAIL": State.FAILED,
        "OUT_OF_MEMORY": State.FAILED, "BOOT_FAIL": State.FAILED, "DEADLINE": State.FAILED,
        "CANCELLED": State.CANCELLED, "PREEMPTED": State.CANCELLED, "TIMEOUT": State.TIMEOUT}


class Slurm(Scheduler):
    name = "slurm"
    prefix = "#SBATCH"

    def directives(self, spec, res, cluster, run_dir):
        d = [f"--job-name={spec.name}", f"--output={run_dir}/stdout.log", f"--error={run_dir}/stderr.log",
             f"--time={res.walltime}", f"--nodes={res.nodes}", f"--ntasks={res.ntasks}",
             f"--ntasks-per-node={res.ntasks // res.nodes}", f"--cpus-per-task={res.cpus_per_task}"]
        if res.mem:
            d.append(f"--mem={parse_mem_mb(res.mem)}M")
        if res.gpus:
            d.append(f"--gpus-per-node={res.gpus}")
        if res.partition:
            d.append(f"--partition={res.partition}")
        if res.account:
            d.append(f"--account={res.account}")
        return [f"{self.prefix} {x}" for x in d] + self.extra(cluster)

    def submit_cmd(self, run_dir):
        return f"cd {run_dir} && sbatch --parsable job.sh"

    def parse_job_id(self, out):
        m = re.match(r"\s*(\d+)", out)
        if not m:
            raise ValueError(f"cannot parse sbatch output: {out!r}")
        return m.group(1)

    def status_cmd(self, job_id):
        return (f"squeue -h -j {job_id} -o '%T|%M|%R' 2>/dev/null; echo '@@'; "
                f"sacct -n -P -X -j {job_id} -o State,ExitCode,Elapsed,NodeList 2>/dev/null")

    def parse_status(self, out):
        live, _, acct = out.partition("@@")
        live = next((l for l in live.splitlines() if l.strip()), "")
        if live:
            st, elapsed, reason = (live.split("|") + ["", ""])[:3]
            return _MAP.get(st.split()[0], State.UNKNOWN), {"elapsed": elapsed, "reason": reason}
        acct = next((l for l in acct.splitlines() if l.strip()), "")
        if acct:
            st, ec, elapsed, nodes = (acct.split("|") + ["", "", ""])[:4]
            return _MAP.get(st.split()[0], State.UNKNOWN), {"elapsed": elapsed, "exit": ec, "nodes": nodes}
        return State.UNKNOWN, {}

    def cancel_cmd(self, job_id):
        return f"scancel {job_id}"
