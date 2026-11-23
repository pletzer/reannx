"""Full lifecycle against fake sbatch/qsub/apptainer; 'remote' is a local directory."""
import os
from pathlib import Path

import pytest

from reannx import state
from reannx.cli import main

FAKEBIN = Path(__file__).parent / "fakebin"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", f"{FAKEBIN}:{os.environ['PATH']}")
    (tmp_path / "sched").mkdir()
    monkeypatch.setenv("FAKE_SCHED_DIR", str(tmp_path / "sched"))
    monkeypatch.setenv("REANNX_STATE", str(tmp_path / "state"))
    (tmp_path / "clusters.toml").write_text(f"""
[clusters.fakeslurm]
scheduler = "slurm"
workdir = "{tmp_path}/remote_slurm"
[clusters.fakepbs]
scheduler = "pbs"
workdir = "{tmp_path}/remote_pbs"
""")
    (tmp_path / "in.txt").write_text("hello\n")
    (tmp_path / "img.sif").write_bytes(b"not really an image")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("cluster", ["fakeslurm", "fakepbs"])
def test_run_cycle(env, cluster, capsys):
    rc = main(["--clusters", "clusters.toml", "run", "-c", cluster, "--image", "img.sif", "--name", "t1",
               "--input", "in.txt", "--output", "out.dat", "--poll", "0.2", "--out", "res",
               "--", "bash", "-c", "tr a-z A-Z < in.txt > out.dat; echo done-$#", "x"])
    assert rc == 0
    run = state.load(None)
    assert run["state"] == "COMPLETED"
    out = Path(run["out_dir"])
    assert (out / "work" / "out.dat").read_text() == "HELLO\n"
    assert "done-0" in (out / "stdout.log").read_text()
    assert (out / "exit_code").read_text().strip() == "0"
    # image uploaded once, cached by hash
    assert len(list((env / f"remote_{cluster[4:]}" / "images").glob("img-*.sif"))) == 1
    capsys.readouterr()
    assert main(["status"]) == 0 and "COMPLETED" in capsys.readouterr().out
    assert main(["logs"]) == 0 and "done" in capsys.readouterr().out
    assert main(["list"]) == 0 and "t1" in capsys.readouterr().out
    assert main(["clean"]) == 0 and not Path(run["run_dir"]).exists()


def test_failure_reported(env):
    rc = main(["--clusters", "clusters.toml", "run", "-c", "fakeslurm", "--image", "img.sif", "--poll", "0.2",
               "--out", "res", "--", "bash", "-c", "echo oops >&2; exit 3"])
    assert rc == 1
    run = state.load(None)
    assert run["state"] == "FAILED"
    assert "oops" in (Path(run["out_dir"]) / "stderr.log").read_text()
    assert (Path(run["out_dir"]) / "exit_code").read_text().strip() == "3"


def test_dry_run_touches_nothing(env, capsys):
    rc = main(["--clusters", "clusters.toml", "run", "--dry-run", "-c", "fakepbs", "--image", "img.sif",
               "-n", "4", "--", "prog"])
    assert rc == 0 and "#PBS -l select=1:ncpus=4:mpiprocs=4" in capsys.readouterr().out
    assert not (env / "remote_pbs").exists() and state.list_ids() == []


def test_config_error(env, capsys):
    rc = main(["--clusters", "clusters.toml", "run", "-c", "nope", "--image", "x", "--", "p"])
    assert rc == 2 and "unknown cluster" in capsys.readouterr().err
