"""Run commands and copy files on a cluster via system ssh/rsync (or locally for tests)."""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

CM_DIR = Path.home() / ".cache" / "reannx" / "cm"


class TransportError(Exception):
    pass


class Transport:
    """host=None runs everything locally (used by the test-suite)."""

    def __init__(self, host: str | None = None, persist: str = "10m"):
        self.host = host
        self.persist = persist

    # -- ssh plumbing --------------------------------------------------
    def _ssh_opts(self) -> list[str]:
        CM_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        # our own control socket: the user's ssh config may use ControlPersist 1
        return ["-o", "ControlMaster=auto", "-o", f"ControlPath={CM_DIR}/%C",
                "-o", f"ControlPersist={self.persist}", "-o", "ServerAliveInterval=30", "-o", "ForwardX11=no"]

    def _remote(self, path: str) -> str:
        return f"{self.host}:{path}" if self.host else path

    def _rsync_base(self) -> list[str]:
        base = ["rsync", "-rlt"]   # no -p/-o/-g: cluster dirs are setgid/ACL-managed
        if self.host:
            base += ["-e", "ssh " + shlex.join(self._ssh_opts())]
        return base

    # -- API -----------------------------------------------------------
    def run(self, cmd: str, check: bool = True, input: str | None = None,
            timeout: float | None = None) -> str:
        argv = (["ssh", *self._ssh_opts(), self.host, cmd] if self.host else ["bash", "-c", cmd])
        p = subprocess.run(argv, input=input, capture_output=True, text=True, timeout=timeout)
        if check and p.returncode != 0:
            raise TransportError(f"command failed ({p.returncode}): {cmd}\n{p.stderr.strip()}")
        return p.stdout

    def write_file(self, remote_path: str, text: str, mode: str = "644"):
        self.run(f"cat > {shlex.quote(remote_path)} && chmod {mode} {shlex.quote(remote_path)}", input=text)

    def put(self, src_base: Path, rel: str, remote_dir: str):
        """Copy src_base/rel to remote_dir/rel (portable: no rsync -R, macOS rsync lacks `/./`)."""
        src = Path(src_base) / rel
        if not src.exists():
            raise TransportError(f"input {src} does not exist")
        parent = str(Path(rel).parent)
        dest = remote_dir if parent == "." else f"{remote_dir}/{parent}"
        self.run(f"mkdir -p {shlex.quote(dest)}")
        self._rsync(str(src).rstrip("/"), self._remote(dest + "/"), "-p")

    def put_file(self, local: Path, remote_path: str):
        self._rsync(str(local), self._remote(remote_path), "-p", "--partial", "--progress" if sys.stderr.isatty() else "-q")

    def get(self, remote_path: str, local_dir: Path, *extra: str):
        local_dir.mkdir(parents=True, exist_ok=True)
        self._rsync(self._remote(remote_path), str(local_dir) + "/", *extra)

    def _rsync(self, src: str, dst: str, *extra: str):
        p = subprocess.run([*self._rsync_base(), *extra, src, dst], capture_output=True, text=True)
        if p.returncode != 0:
            raise TransportError(f"rsync failed ({p.returncode}): {src} -> {dst}\n{p.stderr.strip()}")

    def login(self):
        """Interactive: authenticate (2FA) and leave the control master running."""
        if not self.host:
            return
        subprocess.run(["ssh", *self._ssh_opts(), self.host, "true"], check=True)
