# reannx — Requirements

Status: draft v0.1 (2026-11-24)

## 1. Purpose

`reannx` submits a containerised program from a user's laptop to an HPC
cluster (**mahuika**, SLURM; **cascade**, PBS), lets the user monitor it, and
brings the outputs and logs back to the laptop. The user chooses the target
cluster per run. The user never writes a batch script.

Driving example: `upwindMpiCxx` from [fidibench](https://github.com/pletzer/fidibench),
an MPI C++ program run from an Apptainer image.

## 2. Users and context

- Primary user: a researcher on macOS/Linux with `ssh` access to both clusters
  (already configured in `~/.ssh/config`, possibly through a jump host and
  2-factor authentication).
- The laptop usually has **no Apptainer** (macOS) and may be a different CPU
  architecture (arm64) from the clusters (x86_64).
- Clusters are shared; the tool runs only on the laptop. **Nothing needs to be
  installed on the cluster beyond what is already there** (`apptainer`,
  scheduler client commands, `rsync`/`bash`).

## 3. Definitions

| Term | Meaning |
|------|---------|
| run | one submission: inputs + command + resources → one scheduler job |
| job spec | what the user asks for (image, command, files, resources) |
| cluster profile | per-cluster config: scheduler type, ssh host, paths, limits, templates |
| run dir | per-run directory on the cluster scratch filesystem |

## 4. Functional requirements

Priority: **M** = must (PoC or v1), **S** = should, **C** = could.

### 4.1 Job specification
- **F1 (M)** A job is: container image, command (program + arguments), input
  files, expected output patterns, resources, target cluster.
- **F2 (M)** The spec can come from a TOML file (`reannx.toml`), from command
  line flags, or both (flags override the file).
- **F3 (M)** Image may be (a) a local `.sif` (uploaded, cached by content hash),
  (b) a registry URI (`docker://…`, `oras://…`) pulled on the cluster once and
  cached, or (c) a path already on the cluster (`remote:/path/x.sif`).
- **F4 (M)** Input files/directories are copied to the run dir; the program runs
  with that directory as its working directory.
- **F5 (S)** Environment variables and extra bind mounts can be passed to the
  container.
- **F6 (M)** MPI jobs: a flag selects launching the container through the
  cluster's launcher (`srun` / `mpiexec`) so that all ranks run inside the
  image (Apptainer hybrid model).

### 4.2 Resource mapping
- **F7 (M)** Users state resources scheduler-neutrally: nodes, tasks (MPI
  ranks), CPUs per task, memory, walltime, GPUs, queue/partition, account.
- **F8 (M)** Cluster profiles map these to SLURM `#SBATCH` directives or PBS
  `#PBS -l select=…` / `walltime` lines. The mapping is data/config driven,
  not hard coded per program.
- **F9 (M)** Profiles carry limits (cores/node, memory/node, max walltime).
  Requests are validated *before* submission, with clear errors; missing
  `nodes` is derived from tasks × CPUs ÷ cores per node.
- **F10 (S)** Profiles define default partition/queue, account/project, and
  a `module load` list for the cluster side.
- **F11 (M)** The user can add or override profiles in
  `~/.config/reannx/clusters.toml` without editing the package.

### 4.3 Submission and lifecycle
- **F12 (M)** `submit` uploads, generates the batch script, submits, prints a
  run id, and returns immediately. `run` = submit + wait + fetch.
- **F13 (M)** `--dry-run` prints the generated batch script and the commands that
  would run, touching nothing remote.
- **F14 (M)** `cancel` stops a run (`scancel` / `qdel`).
- **F15 (S)** Retry-safe: a lost connection during `run`/`wait` never loses the
  run; it can be re-attached by id.

### 4.4 Monitoring
- **F16 (M)** `status` reports a normalised state — `PENDING, RUNNING,
  COMPLETED, FAILED, CANCELLED, TIMEOUT, UNKNOWN` — plus scheduler detail
  (elapsed, node list, exit code).
- **F17 (M)** `logs` shows stdout/stderr; `logs -f` follows them while running.
- **F18 (M)** `list` shows all runs known locally with their last state.
- **F19 (M)** Final status is decided robustly: the generated job script writes
  an exit-code file, so a run is correctly reported even after the scheduler
  has forgotten the job.
- **F20 (C)** Resource-efficiency summary after completion (e.g. `sacct`
  MaxRSS vs requested memory).

### 4.5 Results
- **F21 (M)** `fetch` copies stdout, stderr, the exit code and files matching
  the output patterns to a local directory (default `./reannx-out/<run-id>`).
- **F22 (S)** Incremental fetch (rsync) so repeated calls are cheap; large
  outputs can be excluded.
- **F23 (S)** `clean` removes the remote run dir.

### 4.6 Connectivity
- **F24 (M)** All remote access is through the system `ssh`/`rsync` using the
  user's `~/.ssh/config` host aliases (jump hosts, users, keys).
- **F25 (M)** The tool opens its **own** multiplexed ssh connection (own
  `ControlPath`, persists ~10 min) so 2FA is asked once, independent of the
  user's `ControlPersist` setting. `reannx login <cluster>` establishes it
  interactively.

## 5. Non-functional requirements

- **N1** Python ≥ 3.11, standard library only at runtime (no compiled deps,
  `pipx install` / `uv tool install` friendly).
- **N2** macOS and Linux laptops. Windows out of scope.
- **N3** No daemon or service on the cluster; no credentials stored by the tool.
- **N4** Idempotent and inspectable: every run's script, spec and state are
  plain files, locally (`~/.local/state/reannx/runs/<id>/`) and remotely.
- **N5** Testable without a cluster: transport can be swapped for a local one
  and fake `sbatch`/`qsub` scripts.
- **N6** Errors are actionable (which field, which limit, what the cluster
  said).
- **N7** Open source on GitHub; license to be chosen by the author.

## 6. Constraints, assumptions, risks

| # | Item |
|---|------|
| A1 | Images are **linux/amd64**. Building on an Apple-silicon laptop gives arm64 images that will not run on the clusters. The tool should warn; building is out of scope (use cluster-side build, CI, or `docker buildx --platform linux/amd64`). |
| A2 | Containerised MPI needs an ABI-compatible MPI inside the image vs. the host (fidibench's Intel job binds host Intel MPI into the container). The tool exposes `binds`, `env`, `modules` and a `launcher` template to express this; it does not solve MPI compatibility itself. |
| A3 | Compute nodes may have no internet; registry pulls happen on the login node (or via the tool's `pull` step). |
| A4 | cascade scheduler is assumed to be **PBS Pro** and its profile values (queue names, cores/node, project flag) are **unverified**; cascade login hosts were not resolvable from the dev network (likely VPN/NIWA network only). |
| A5 | mahuika limits (partitions `genoa`, `milan`, `hugemem`; `--account` required) were read from the live cluster on 2026-11-24. |
| A6 | Scratch path conventions (`/nesi/nobackup/<project>/…` on mahuika) are profile config. |
| A7 | Jobs consume the user's allocation; the tool never submits without an explicit command from the user. |

## 6b. Out of scope (v1)
Workflow DAGs (use Nextflow/Snakemake/Cylc), job arrays/parameter sweeps,
building containers, a GUI/web dashboard, multi-user service mode, data
staging via Globus.

## 7. Acceptance for the proof-of-concept
1. `reannx run --dry-run` for upwindMpiCxx on both profiles prints correct
   SLURM and PBS scripts for the same spec.
2. Against fake `sbatch/squeue/sacct` and `qsub/qstat`, a full
   submit → status → logs → fetch cycle passes in automated tests.
3. Against **mahuika** (real), the upwindMpiCxx example runs from the laptop
   with logs and outputs returned. *(needs the user's go-ahead and account)*
4. cascade: dry-run output reviewed by the user; real run deferred until the
   profile is verified.
