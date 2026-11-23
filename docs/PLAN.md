# reannx — Tool choices and plan

## 1. Tool choices

| Concern | Choice | Why / alternatives rejected |
|---------|--------|-----------------------------|
| Language | Python 3.11+ | `tomllib` in stdlib; easy to install with pipx/uv; user's existing tooling is Python. Go would give one static binary, but slower to iterate. |
| Dependencies | **none at runtime** | Keeps install trivial. `argparse` for CLI (typer/click rejected: not worth a dep for ~10 subcommands). |
| Config format | TOML | stdlib reader; comments; fine for profiles and job specs. YAML rejected (needs PyYAML). |
| Remote access | system `ssh` + `rsync` via `subprocess` | Reuses `~/.ssh/config` (ProxyCommand, users, keys, 2FA). paramiko/fabric rejected: don't read ProxyCommand/2FA setups reliably. |
| Connection reuse | OpenSSH `ControlMaster` with reannx's own `ControlPath`, `ControlPersist=10m` | The user's config has `ControlPersist 1`, which would re-authenticate on every call. |
| Scheduler abstraction | small `Scheduler` class per backend (`slurm`, `pbs`): render directives, submit, status, cancel, parse | Adding a scheduler = one file. |
| Remote execution | generated `job.sh` + wrapper that writes `started`, `exit_code`, `finished` files | Status survives scheduler forgetting the job (F19). |
| Container runtime | `apptainer exec` on the cluster | Matches requirement; image pull/cache on cluster. |
| Packaging | `pyproject.toml` (setuptools, src layout), `uv`/`pipx` | |
| Tests | `pytest`; a `Transport` with `host=None` runs "remotely" in a local temp dir against fake `sbatch/squeue/sacct/qsub/qstat/apptainer` scripts | Full lifecycle tested with no cluster. |
| CI | GitHub Actions (pytest, ruff) — v0.2 | |

## 2. Architecture

```
reannx CLI ──► JobSpec (file + flags) ──► ClusterProfile (clusters.toml)
                    │                         │
                    ▼                         ▼
              Scheduler.render()  ◄── resource mapping + limits
                    │
        Transport (ssh/rsync | local) ──► cluster: <workdir>/reannx/<run-id>/
                                              job.sh  work/  stdout.log stderr.log
                                              started exit_code finished
        local state: ~/.local/state/reannx/runs/<run-id>/run.json
```

Run lifecycle: `prepare → upload → submit → (status/logs)* → fetch → clean`.

Remote layout per run:
`<workdir>/reannx/<run-id>/{job.sh,work/,stdout.log,stderr.log,started,exit_code,finished}`
and a shared `<workdir>/reannx/images/` image cache.

## 3. Milestones

| M | Deliverable | State |
|---|-------------|-------|
| 0 | Requirements, plan (this doc) | done |
| 1 | PoC: spec, profiles, SLURM + PBS rendering, submit/status/logs/fetch/cancel/list, dry-run, local-fake tests | **done 2026-11-24** (12 tests) |
| 2 | Real run on mahuika with upwindMpiCxx image | **done 2026-11-24** (2 nodes x 2 ranks, hybrid MPI via setup_file) |
| 3 | Verify cascade profile (queues, select syntax, project flag, modules); real run | needs VPN/network |
| 4 | Efficiency report (sacct), `clean`, incremental log follow, GitHub Actions, README | |
| 5 | `reannx build` helper (remote `apptainer build`, like `fidibench_apptainer_build.sl`) | optional |

## 4. PoC scope decisions

- Included: everything in requirements marked M except real-cluster runs.
- Cascade profile is a **draft** with limits left unset; flagged in the file.
- MPI uses a `launcher` template per profile (`srun` on mahuika, `mpiexec` on
  cascade). Host-MPI binding (fidibench intel recipe) is expressed via `binds`/`env`/`modules`.

## 5. Open questions for the user
1. Which mahuika account/project should real test jobs be charged to?
2. Is there a built x86_64 fidibench `.sif` on mahuika (or a registry URI) to use?
3. Cascade: PBS Pro? queue names, cores per node, project flag, `module` for apptainer, network access path?
4. License choice for the GitHub repo.
