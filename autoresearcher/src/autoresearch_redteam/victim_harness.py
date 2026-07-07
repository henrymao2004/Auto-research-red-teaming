"""Model-agnostic host-side docker harness shared by victim adapters."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def run_in_docker(
    image: str,
    spec_json: str,
    container_env: dict[str, str],
    *,
    work_tmpfs_size: str = "2g",
    cpus: float = 2.0,
    memory: str = "4g",
    timeout_seconds: int = 600,
    plugins_dir: Path | None = None,
) -> dict[str, Any]:
    """Spawn one ``docker run --rm -i`` container; return the parsed trajectory."""
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="ar_") as tmpdir:
        tmpdir = Path(tmpdir)
        workdir = tmpdir / "work"
        harness_dir = tmpdir / "harness"
        workdir.mkdir()
        harness_dir.mkdir()
        try:
            proc = _docker_run(
                workdir, harness_dir, image, spec_json, container_env,
                work_tmpfs_size=work_tmpfs_size, cpus=cpus, memory=memory,
                timeout_seconds=timeout_seconds, plugins_dir=plugins_dir,
            )
        except subprocess.TimeoutExpired as _te:
            _se = _te.stderr
            if isinstance(_se, (bytes, bytearray)):
                _se = _se.decode("utf-8", "replace")
            _so = _te.stdout
            if isinstance(_so, (bytes, bytearray)):
                _so = _so.decode("utf-8", "replace")
            return {"_container": {"rc": -1,
                                   "stderr_tail": (_se or "")[-4000:],
                                   "stdout_tail": (_so or "")[-2000:],
                                   "error": "container timed out",
                                   "image": image,
                                   "duration_seconds": time.time() - t0}}
        except Exception as e:
            return {"_container": {"rc": -1, "stderr_tail": "",
                                   "error": f"docker error: {e}",
                                   "image": image,
                                   "duration_seconds": time.time() - t0}}

        traj_path = harness_dir / "trajectory.json"
        if not traj_path.exists():
            return {"_container": {
                "rc": proc.returncode,
                "stderr_tail": (proc.stderr or "")[-2000:],
                "error": "container exited without writing trajectory.json",
                "image": image,
                "duration_seconds": time.time() - t0,
            }}
        parsed = json.loads(traj_path.read_text())
        parsed["_container"] = {
            "rc": proc.returncode,
            "stderr_tail": (proc.stderr or "")[-2000:],
            "image": image,
            "duration_seconds": time.time() - t0,
            "error": None,
        }
        return parsed


def _docker_run(
    workdir: Path,
    harness_dir: Path,
    image: str,
    spec_json: str,
    container_env: dict[str, str],
    *,
    work_tmpfs_size: str,
    cpus: float,
    memory: str,
    timeout_seconds: int,
    plugins_dir: Path | None,
) -> subprocess.CompletedProcess:
    cmd = [
        "docker", "run", "--rm", "-i",
        "--cpus", str(cpus),
        "--memory", memory,
    ]
    _dbg_name = os.environ.get("AR_DEBUG_CONTAINER_NAME")
    if _dbg_name:
        cmd += ["--name", _dbg_name]
    cmd += [
        # Mount capped work tmpfs.
        "--tmpfs", f"/work:rw,size={work_tmpfs_size},mode=1777",
        "-v", f"{harness_dir}:/harness",
    ]
    if plugins_dir is not None:
        cmd += ["-v", f"{plugins_dir}:/plugins:ro"]
    for key, value in container_env.items():
        cmd += ["-e", f"{key}={value}"]
    cmd += [image]
    return subprocess.run(
        cmd, input=spec_json, capture_output=True, text=True,
        timeout=timeout_seconds,
    )
