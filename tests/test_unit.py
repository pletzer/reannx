import pytest

from reannx.config import ConfigError, Cluster, Resources, JobSpec, parse_mem_mb, parse_walltime
from reannx.runner import render_script
from reannx.schedulers import State, get_scheduler


def cluster(sched="slurm", **kw):
    return Cluster(name="t", scheduler=sched, ssh_host=None, workdir="/w/{account}/{user}",
                   account="acc", user="u", **kw)


def test_walltime():
    assert parse_walltime("10") == 600
    assert parse_walltime("05:30") == 330
    assert parse_walltime("1-12") == 129600
    assert parse_walltime("21-00:00:00") == 21 * 86400
    with pytest.raises(ConfigError):
        parse_walltime("abc")


def test_mem():
    assert parse_mem_mb("2G") == 2048 and parse_mem_mb("500M") == 500 and parse_mem_mb(100) == 100


def test_validate_derives_nodes_and_limits():
    c = cluster(limits={"cores_per_node": 8, "mem_per_node_gb": 16, "max_walltime": "01:00:00"})
    assert c.validate(Resources(ntasks=16)).nodes == 2
    with pytest.raises(ConfigError, match="cores/node"):
        c.validate(Resources(ntasks=16, nodes=1))
    with pytest.raises(ConfigError, match="mem"):
        c.validate(Resources(mem="32G"))
    with pytest.raises(ConfigError, match="walltime"):
        c.validate(Resources(walltime="02:00:00"))
    with pytest.raises(ConfigError, match="divisible"):
        c.validate(Resources(ntasks=3, nodes=2))


def spec(**kw):
    return JobSpec(name="j", cluster="t", image="remote:/i.sif", command=["prog", "-a", "x y"], **kw)


def test_slurm_script():
    c = cluster(limits={"cores_per_node": 8})
    r = c.validate(Resources(ntasks=8, nodes=2, cpus_per_task=1, mem="4G", walltime="00:05:00"))
    s = render_script(spec(mpi=True), c, r, "/w/run1", "/i.sif")
    for want in ("#SBATCH --nodes=2", "#SBATCH --ntasks-per-node=4", "#SBATCH --mem=4096M",
                 "#SBATCH --account=acc", "#SBATCH --time=00:05:00",
                 "srun apptainer exec", "prog -a 'x y'"):
        if want == "srun apptainer exec":
            c.launcher = "srun"
            s = render_script(spec(mpi=True), c, r, "/w/run1", "/i.sif")
        assert want in s, want


def test_pbs_script():
    c = cluster("pbs", defaults={"queue": "q1"})
    r = c.validate(Resources(ntasks=8, nodes=2, cpus_per_task=2, mem="8G", walltime="30"))
    s = render_script(spec(), c, r, "/w/run1", "/i.sif")
    assert "#PBS -l select=2:ncpus=8:mpiprocs=4:ompthreads=2:mem=8192mb" in s
    assert "#PBS -l walltime=00:30:00" in s and "#PBS -q q1" in s and "#PBS -P acc" in s


def test_slurm_status_parsing():
    s = get_scheduler("slurm")
    assert s.parse_status("RUNNING|0:05|node1\n@@\n")[0] == State.RUNNING
    assert s.parse_status("@@\nCANCELLED by 123|0:0|00:01:00|n1\n")[0] == State.CANCELLED
    assert s.parse_status("@@\nTIMEOUT|0:0|00:01:00|n1\n")[0] == State.TIMEOUT
    assert s.parse_status("@@\n")[0] == State.UNKNOWN


def test_pbs_status_parsing():
    s = get_scheduler("pbs")
    assert s.parse_status("    job_state = Q\n")[0] == State.PENDING
    assert s.parse_status("    job_state = F\n    Exit_status = 2\n")[0] == State.FAILED
    assert s.parse_status("")[0] == State.UNKNOWN


def test_queue_limits_override():
    c = cluster("pbs", defaults={"queue": "shortq"}, limits={"cores_per_node": 8},
                queues={"shortq": {"max_walltime": "48:00:00"}, "longq": {"max_walltime": "336:00:00"}})
    with pytest.raises(ConfigError, match="walltime"):
        c.validate(Resources(walltime="72:00:00"))
    assert c.validate(Resources(walltime="72:00:00", partition="longq")).partition == "longq"


def test_cluster_default_binds_and_dedup():
    c = cluster(binds=["/nesi/project", "/nesi/nobackup"])
    r = c.validate(Resources())
    s = render_script(spec(binds=["/nesi/nobackup", "/extra"]), c, r, "/w/run1", "/i.sif")
    assert "REANNX_BINDS=/w/run1,/nesi/project,/nesi/nobackup,/extra\n" in s
