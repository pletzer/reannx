"""Local run records: ~/.local/state/reannx/runs/<id>/run.json"""
from __future__ import annotations

import json
import os
from pathlib import Path


def state_dir() -> Path:
    return Path(os.environ.get("REANNX_STATE", Path.home() / ".local" / "state" / "reannx")) / "runs"


def save(run: dict):
    d = state_dir() / run["id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "run.json").write_text(json.dumps(run, indent=2))


def load(run_id: str | None) -> dict:
    ids = list_ids()
    if run_id is None:
        if not ids:
            raise KeyError("no runs recorded yet")
        run_id = ids[-1]
    cand = [i for i in ids if i == run_id] or [i for i in ids if i.startswith(run_id)]
    if len(cand) != 1:
        raise KeyError(f"run {run_id!r}: {'not found' if not cand else 'ambiguous'}")
    return json.loads((state_dir() / cand[0] / "run.json").read_text())


def list_ids() -> list[str]:
    d = state_dir()
    return sorted(p.name for p in d.iterdir() if (p / "run.json").exists()) if d.exists() else []
