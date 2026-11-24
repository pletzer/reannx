# reannx

Submit a containerised (Apptainer) program from your laptop to **mahuika** (SLURM) or
**cascade** (PBS), watch it, and get logs and outputs back. Uses your `~/.ssh/config`
aliases, system `ssh`/`rsync`, and no dependencies. Status: proof of concept.

```bash
uv venv && uv pip install -e '.[test]'     # or: python -m venv .venv && .venv/bin/pip install -e '.[test]'
reannx login mahuika                       # 2FA once; connection reused ~10 min
cd examples/upwind                         # edit the <project>/<user> placeholders in mahuika.toml or cascade.toml
reannx run -f mahuika.toml --dry-run       # print job.sh, touch nothing
reannx run -f mahuika.toml --follow        # submit, stream stdout, fetch results to ./reannx-out/<id>
reannx submit … ; reannx status|logs -f|fetch|cancel|clean|list [id]
```

Ad hoc, without a spec file:

```bash
reannx run -c mahuika -A <project> --image remote:/path/x.sif -N 2 -n 4 --mem 4G -t 00:05 --mpi \
  --input data.nc --output '*.vtk' -- /app/prog -arg 1
```

* A job spec (default `./reannx.toml`, or `-f FILE`; see `examples/upwind/mahuika.toml` and `cascade.toml`) holds image, command, inputs/outputs, resources.
  Resources are scheduler-neutral and mapped to `#SBATCH` or `#PBS -l select=…`.
* Cluster profiles: `src/reannx/data/clusters.toml`; override in `~/.config/reannx/clusters.toml`.
  The **cascade profile is an unverified draft**.
* Images: local `.sif` (uploaded, cached by hash), `docker://…` (pulled on the cluster),
  or `remote:/path.sif`. Images must be linux/amd64.
* Hybrid-MPI plumbing (host PMI/UCX binds) lives in a `setup_file` shell snippet that may append to `$REANNX_BINDS`.
* Tests: `pytest` (fake `sbatch/squeue/sacct/qsub/qstat/apptainer` in `tests/fakebin`).

## License

MIT, see `LICENSE`.

See `docs/REQUIREMENTS.md` and `docs/PLAN.md`.
