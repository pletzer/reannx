from .base import Scheduler, State
from .pbs import PBS
from .slurm import Slurm

SCHEDULERS = {"slurm": Slurm, "pbs": PBS}


def get_scheduler(name: str) -> Scheduler:
    try:
        return SCHEDULERS[name]()
    except KeyError:
        raise ValueError(f"unknown scheduler {name!r}; known: {sorted(SCHEDULERS)}") from None


__all__ = ["Scheduler", "State", "get_scheduler"]
