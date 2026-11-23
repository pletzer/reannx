from __future__ import annotations

import re

from ..config import fmt_walltime, parse_mem_mb, parse_walltime
from .base import Scheduler, State

_MAP = {"Q": State.PENDING, "H": State.PENDING, "W": State.PENDING, "T": State.PENDING, "S": State.PENDING,
        "R": State.RUNNING, "E": State.RUNNING, "B": State.RUNNING}


class PBS(Scheduler):
    """PBS Pro. cascade profile is UNVERIFIED (see clusters.toml)."""
    name = "pbs"
    prefix = "#PBS"

    def directives(self, spec, res, cluster, run_dir):
        tpn = res.ntasks // res.nodes
        sel = f"select={res.nodes}:ncpus={tpn * res.cpus_per_task}:mpiprocs={tpn}"
        if res.cpus_per_task > 1:
            sel += f":ompthreads={res.cpus_per_task}"
        if res.mem:
            sel += f":mem={parse_mem_mb(res.mem)}mb"
        if res.gpus:
            sel += f":ngpus={res.gpus}"
        d = [f"-N {spec.name[:15]}", f"-o {run_dir}/stdout.log", f"-e {run_dir}/stderr.log",
             f"-l {sel}", f"-l walltime={fmt_walltime(parse_walltime(res.walltime))}"]
        if res.partition:
            d.append(f"-q {res.partition}")
        if res.account:
            d.append(f"{cluster.defaults.get('account_flag', '-P')} {res.account}")
        return [f"{self.prefix} {x}" for x in d] + self.extra(cluster)

    def submit_cmd(self, run_dir):
        return f"cd {run_dir} && qsub job.sh"

    def parse_job_id(self, out):
        m = re.match(r"\s*(\S+)", out)
        if not m:
            raise ValueError(f"cannot parse qsub output: {out!r}")
        return m.group(1)

    def status_cmd(self, job_id):
        return f"qstat -x -f {job_id} 2>/dev/null"

    def parse_status(self, out):
        kv = dict(re.findall(r"^\s*(\w+) = (.*)$", out, re.M))
        js = kv.get("job_state")
        if not js:
            return State.UNKNOWN, {}
        info = {"elapsed": kv.get("resources_used.walltime", ""), "nodes": kv.get("exec_host", "")}
        if js == "F":
            ec = kv.get("Exit_status")
            info["exit"] = ec or ""
            return (State.COMPLETED if ec == "0" else State.FAILED), info
        return _MAP.get(js, State.UNKNOWN), info

    def cancel_cmd(self, job_id):
        return f"qdel {job_id}"
