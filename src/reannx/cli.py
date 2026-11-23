"""reannx command line."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, runner, state
from .config import ConfigError, JobSpec, load_clusters, load_spec
from .transport import TransportError


def _add_job_args(p: argparse.ArgumentParser):
    p.add_argument("-f", "--file", type=Path, help="job spec (reannx.toml)")
    p.add_argument("-c", "--cluster")
    p.add_argument("--image")
    p.add_argument("--name")
    p.add_argument("--mpi", action="store_true", default=None, help="launch ranks through the cluster launcher")
    p.add_argument("--launcher", help='override launcher, e.g. "srun --mpi=pmi2"')
    p.add_argument("-N", "--nodes", type=int)
    p.add_argument("-n", "--ntasks", type=int)
    p.add_argument("--cpus-per-task", type=int)
    p.add_argument("--mem", help="per node, e.g. 8G")
    p.add_argument("-t", "--time", dest="walltime", help="[D-]HH:MM:SS")
    p.add_argument("--gpus", type=int)
    p.add_argument("-p", "--partition", help="SLURM partition / PBS queue")
    p.add_argument("-A", "--account")
    p.add_argument("--input", action="append", default=[], help="file/dir to copy to the run dir (repeatable)")
    p.add_argument("--output", action="append", default=[], help="output glob to fetch (repeatable)")
    p.add_argument("--env", action="append", default=[], metavar="K=V")
    p.add_argument("--bind", action="append", default=[])
    p.add_argument("--out", type=Path, default=Path("reannx-out"), help="local results dir (default ./reannx-out)")
    p.add_argument("--dry-run", action="store_true", help="print the job script, change nothing")
    p.add_argument("command", nargs="*", help="after `--`: program and arguments")


def build_spec(a) -> JobSpec:
    if a.file is None and Path("reannx.toml").exists():
        a.file = Path("reannx.toml")
    s = load_spec(a.file)
    for k in ("cluster", "image", "name", "launcher"):
        if getattr(a, k):
            setattr(s, k, getattr(a, k))
    if a.mpi:
        s.mpi = True
    for k in ("nodes", "ntasks", "cpus_per_task", "mem", "walltime", "gpus", "partition", "account"):
        if getattr(a, k) is not None:
            setattr(s.resources, k, getattr(a, k))
    s.inputs += a.input
    s.outputs += a.output
    s.binds += a.bind
    s.env.update(dict(e.split("=", 1) for e in a.env))
    if a.command:
        s.command = a.command
    if a.file is None and not a.name:
        s.name = "reannx"
    return s


def _cluster(a, spec):
    clusters = load_clusters(Path(a.clusters) if a.clusters else None)
    if spec.cluster not in clusters:
        raise ConfigError(f"unknown cluster {spec.cluster!r}; known: {', '.join(clusters)}")
    return clusters[spec.cluster]


def cmd_submit(a, wait=False):
    spec = build_spec(a)
    spec.check()
    cl = _cluster(a, spec)
    if a.dry_run:
        plan = runner.make_plan(spec, cl, "DRYRUN")
        print("# --- steps (nothing executed) ---")
        for s in plan.steps:
            print("#", s)
        print("# --- job.sh ---")
        print(plan.script)
        return 0
    run = runner.submit(spec, cl, a.out, log=lambda m: print(m, file=sys.stderr))
    print(run["id"])
    if wait:
        st = runner.wait(run, a.poll, a.follow, log=lambda m: print(m, file=sys.stderr))
        out = runner.fetch(run)
        print(f"results in {out}", file=sys.stderr)
        return 0 if st == runner.State.COMPLETED else 1
    return 0


def cmd_status(a):
    ids = [a.id] if a.id or not a.all else state.list_ids()
    for i in ids:
        run = state.load(i)
        st, info = runner.status(run)
        print(f"{run['id']}  {run['cluster']:8} job {run['job_id']:>8}  {st.value:10} "
              f"{info.get('elapsed', '')} {('exit=' + info['exit']) if info.get('exit') else ''}".rstrip())
    return 0


def cmd_list(a):
    for i in state.list_ids():
        r = state.load(i)
        print(f"{r['id']}  {r['cluster']:8} job {r['job_id']:>8}  {r['state']:10} {r['name']}")
    return 0


def cmd_logs(a):
    run = state.load(a.id)
    which = "stderr" if a.stderr else "stdout"
    if not a.follow:
        print(runner.logs(run, which), end="")
        return 0
    off = 0
    while True:
        chunk = runner.logs(run, which, off)
        print(chunk, end="", flush=True)
        off += len(chunk.encode())
        st, _ = runner.status(run)
        if st.terminal:
            print(runner.logs(run, which, off), end="")
            return 0
        import time; time.sleep(a.poll)


def cmd_fetch(a):
    print(runner.fetch(state.load(a.id), a.out))
    return 0


def cmd_cancel(a):
    runner.cancel(state.load(a.id))
    return 0


def cmd_clean(a):
    runner.clean(state.load(a.id))
    return 0


def cmd_login(a):
    from .transport import Transport
    Transport(load_clusters(Path(a.clusters) if a.clusters else None)[a.cluster].ssh_host).login()
    return 0


def cmd_clusters(a):
    for n, c in load_clusters(Path(a.clusters) if a.clusters else None).items():
        print(f"{n:10} {c.scheduler:6} ssh={c.ssh_host} workdir={c.workdir} limits={c.limits or '-'}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="reannx", description=__doc__)
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("--clusters", default=os.environ.get("REANNX_CLUSTERS_FILE"), help="extra clusters.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, h in (("submit", "upload, submit, return"), ("run", "submit, wait, fetch")):
        p = sub.add_parser(name, help=h)
        _add_job_args(p)
        p.add_argument("--poll", type=float, default=10)
        if name == "run":
            p.add_argument("--follow", action="store_true", help="stream stdout while waiting")
    for name, fn, h in (("status", cmd_status, "show state"), ("logs", cmd_logs, "show stdout/stderr"),
                        ("fetch", cmd_fetch, "copy results back"), ("cancel", cmd_cancel, "cancel the job"),
                        ("clean", cmd_clean, "delete remote run dir")):
        p = sub.add_parser(name, help=h)
        p.add_argument("id", nargs="?", help="run id (default: latest)")
        if name == "status":
            p.add_argument("--all", action="store_true")
        if name == "logs":
            p.add_argument("-f", "--follow", action="store_true")
            p.add_argument("--stderr", action="store_true")
            p.add_argument("--poll", type=float, default=3)
        if name == "fetch":
            p.add_argument("--out", type=Path)
        p.set_defaults(fn=fn)
    sub.add_parser("list", help="list known runs").set_defaults(fn=cmd_list)
    sub.add_parser("clusters", help="list cluster profiles").set_defaults(fn=cmd_clusters)
    p = sub.add_parser("login", help="authenticate once (2FA) and keep the connection open")
    p.add_argument("cluster")
    p.set_defaults(fn=cmd_login)

    args = ap.parse_args(argv)
    try:
        if args.cmd == "submit":
            return cmd_submit(args)
        if args.cmd == "run":
            return cmd_submit(args, wait=True)
        return args.fn(args)
    except (ConfigError, TransportError, KeyError, ValueError) as e:
        print(f"reannx: error: {e.args[0] if isinstance(e, KeyError) else e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted (the job, if submitted, keeps running; use `reannx status`)", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
