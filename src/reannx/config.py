"""Cluster profiles and job specs (TOML)."""
from __future__ import annotations

import getpass
import math
import re
import subprocess
import tomllib
from dataclasses import dataclass, field, replace
from importlib import resources
from pathlib import Path


class ConfigError(Exception):
    pass


def _ssh_user(host: str | None) -> str:
    """Login name ssh would use for host (reads ~/.ssh/config locally; no connection made)."""
    if host:
        try:
            out = subprocess.run(["ssh", "-G", host], capture_output=True, text=True, timeout=10).stdout
            for line in out.splitlines():
                if line.startswith("user "):
                    return line.split(None, 1)[1].strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return getpass.getuser()


USER_CLUSTERS = Path.home() / ".config" / "reannx" / "clusters.toml"


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def parse_walltime(s: str) -> int:
    """SLURM-style '[D-]HH[:MM[:SS]]', else 'MM', 'MM:SS', 'HH:MM:SS' -> seconds."""
    m = re.fullmatch(r"(?:(\d+)-)?(\d+(?::\d+){0,2})", str(s).strip())
    if not m:
        raise ConfigError(f"bad walltime {s!r}; use [D-]HH:MM:SS")
    d, rest = m.groups()
    p = [int(x) for x in rest.split(":")]
    if d is not None:
        p = (p + [0, 0])[:3]                   # D-HH[:MM[:SS]]
    elif len(p) == 1:
        p = [0, p[0], 0]                       # MM
    elif len(p) == 2:
        p = [0, p[0], p[1]]                    # MM:SS
    return int(d or 0) * 86400 + p[0] * 3600 + p[1] * 60 + p[2]


def fmt_walltime(sec: int) -> str:
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def parse_mem_mb(s: str | int) -> int:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kKmMgGtT]?)[bB]?", str(s).strip())
    if not m:
        raise ConfigError(f"bad memory {s!r}; use e.g. 500M, 8G")
    n, u = float(m.group(1)), m.group(2).upper() or "M"
    return int(math.ceil(n * {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024**2}[u]))


@dataclass
class Resources:
    nodes: int | None = None
    ntasks: int = 1
    cpus_per_task: int = 1
    mem: str | None = None          # per node, e.g. "8G"
    walltime: str = "00:10:00"
    gpus: int = 0
    partition: str | None = None    # SLURM partition / PBS queue
    account: str | None = None


@dataclass
class Cluster:
    name: str
    scheduler: str
    ssh_host: str | None
    workdir: str
    launcher: str = ""
    binds: list[str] = field(default_factory=list)   # default container bind mounts
    modules: list[str] = field(default_factory=list)
    account: str | None = None
    defaults: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)
    queues: dict = field(default_factory=dict)      # per partition/queue overrides of limits
    user: str | None = None            # remote login name; default: from `ssh -G <host>`

    def __post_init__(self):
        if not self.user:
            self.user = _ssh_user(self.ssh_host)

    def remote_root(self, account: str | None = None) -> str:
        acct = account or self.account
        if "{account}" in self.workdir and not acct:
            raise ConfigError(f"cluster {self.name!r} needs an account (set `account` in "
                              f"{USER_CLUSTERS} or pass --account)")
        return self.workdir.format(account=acct, user=self.user)

    def validate(self, r: Resources) -> Resources:
        """Fill derived fields and check limits; return a new Resources."""
        r = replace(r)
        r.partition = r.partition or self.defaults.get("partition") or self.defaults.get("queue")
        L = {**self.limits, **self.queues.get(r.partition, {})}
        r.account = r.account or self.account
        if r.ntasks < 1 or r.cpus_per_task < 1:
            raise ConfigError("ntasks and cpus_per_task must be >= 1")
        cpn = L.get("cores_per_node")
        if r.nodes is None:
            r.nodes = max(1, math.ceil(r.ntasks * r.cpus_per_task / cpn)) if cpn else 1
        if cpn and (r.ntasks / r.nodes) * r.cpus_per_task > cpn:
            raise ConfigError(f"{self.name}: {r.ntasks} tasks x {r.cpus_per_task} cpus on "
                              f"{r.nodes} node(s) exceeds {cpn} cores/node")
        if r.ntasks % r.nodes:
            raise ConfigError(f"ntasks={r.ntasks} not divisible by nodes={r.nodes}")
        if r.mem and L.get("mem_per_node_gb") and parse_mem_mb(r.mem) > L["mem_per_node_gb"] * 1024:
            raise ConfigError(f"{self.name}: mem {r.mem} exceeds {L['mem_per_node_gb']}G/node")
        if L.get("max_walltime") and parse_walltime(r.walltime) > parse_walltime(L["max_walltime"]):
            raise ConfigError(f"{self.name}: walltime {r.walltime} exceeds {L['max_walltime']}")
        return r


def load_clusters(extra: Path | None = None) -> dict[str, Cluster]:
    data = tomllib.loads(resources.files("reannx").joinpath("data/clusters.toml").read_text())
    for p in (USER_CLUSTERS, extra):
        if p and Path(p).exists():
            data = _merge(data, tomllib.loads(Path(p).read_text()))
    out = {}
    for name, c in data.get("clusters", {}).items():
        try:
            out[name] = Cluster(name=name, scheduler=c["scheduler"], ssh_host=c.get("ssh_host"),
                                workdir=c["workdir"], launcher=c.get("launcher", ""), binds=c.get("binds", []),
                                modules=c.get("modules", []), account=c.get("account"), user=c.get("user"),
                                defaults=c.get("defaults", {}), limits=c.get("limits", {}),
                                queues=c.get("queues", {}))
        except KeyError as e:
            raise ConfigError(f"cluster {name!r}: missing key {e}") from None
    return out


@dataclass
class JobSpec:
    name: str = "reannx"
    cluster: str | None = None
    image: str | None = None
    command: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    mpi: bool = False
    launcher: str | None = None      # overrides the cluster launcher (e.g. "srun --mpi=pmi2")
    setup: list[str] = field(default_factory=list)   # shell lines run in the job before the container
    env: dict[str, str] = field(default_factory=dict)
    binds: list[str] = field(default_factory=list)
    resources: Resources = field(default_factory=Resources)
    base_dir: Path = field(default_factory=Path.cwd)   # inputs are relative to this

    def check(self):
        if not self.image:
            raise ConfigError("no container image (job.image / --image)")
        if not self.command:
            raise ConfigError("no command (job.command / after `--`)")
        if not self.cluster:
            raise ConfigError("no cluster chosen (job.cluster / --cluster)")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", self.name):
            raise ConfigError(f"job name {self.name!r}: use letters, digits, _ . -")


def _setup(j: dict, base: Path) -> list[str]:
    lines = list(j.get("setup", []))
    if j.get("setup_file"):
        lines += (base / j["setup_file"]).read_text().splitlines()
    return lines


def load_spec(path: Path | None) -> JobSpec:
    if path is None:
        return JobSpec()
    d = tomllib.loads(Path(path).read_text())
    j, r = d.get("job", {}), d.get("resources", {})
    unknown = set(j) - {"name", "cluster", "image", "command", "inputs", "outputs", "mpi", "env", "binds",
                      "launcher", "setup", "setup_file"}
    if unknown:
        raise ConfigError(f"{path}: unknown [job] keys {sorted(unknown)}")
    try:
        res = Resources(**r)
    except TypeError as e:
        raise ConfigError(f"{path}: bad [resources]: {e}") from None
    cmd = j.get("command", [])
    return JobSpec(name=j.get("name", Path(path).resolve().parent.name or "reannx"),
                   cluster=j.get("cluster"), image=j.get("image"),
                   command=cmd.split() if isinstance(cmd, str) else list(cmd),
                   inputs=j.get("inputs", []), outputs=j.get("outputs", []),
                   mpi=j.get("mpi", False), launcher=j.get("launcher"),
                   setup=_setup(j, Path(path).resolve().parent), env=j.get("env", {}), binds=j.get("binds", []),
                   resources=res, base_dir=Path(path).resolve().parent)
