"""
project_mcp/sandbox_client.py — Secure code execution sandbox.

Extends the original sandbox_client.py (which used MCP/SSE).
Execution order:
  1. Docker container (syslens-sandbox image) — fully isolated, no network
  2. Subprocess fallback — used when Docker is not available (local dev)

Logging:
  Every stage is logged at DEBUG/INFO level.
  Full stdout + stderr always printed to terminal for easy debugging.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Callable

from ..models import SandboxResult
from ..config import settings

# ── Logger ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("syslens.sandbox")

# ── Code harness ───────────────────────────────────────────────────────────────
_HARNESS = textwrap.dedent("""
import sys, json, traceback, warnings
warnings.filterwarnings('ignore')

try:
{user_code}

    if 'output' not in dir():
        raise RuntimeError("Code must assign result to variable named 'output'")

    print("__OUTPUT_START__")
    print(json.dumps(output, default=str))

except Exception:
    print("__ERROR_START__", file=sys.stderr)
    print(json.dumps({{"error": traceback.format_exc()}}), file=sys.stderr)
    sys.exit(1)
""")


def _indent(code: str, spaces: int = 4) -> str:
    return textwrap.indent(code, " " * spaces)


class SandboxClient:
    """
    Runs Python code in an isolated environment.
    Inherits the concept from original project_mcp/sandbox_client.py.
    """

    def __init__(self):
        self._docker_available = self._check_docker()
        if self._docker_available:
            logger.info("Sandbox: Docker is available — will use container isolation")
        else:
            logger.warning("Sandbox: Docker NOT found — using subprocess fallback (dev mode)")
            logger.info(f"Sandbox: sys.executable = {sys.executable}")

    def execute(
        self,
        code: str,
        file_bytes: bytes | None = None,
        filename: str = "data.csv",
        progress_cb: Callable[[str], None] | None = None,
    ) -> SandboxResult:
        logger.info(f"Sandbox.execute() — file={filename} code_lines={len(code.splitlines())}")
        logger.debug(f"Sandbox code preview:\n{code[:800]}\n{'...' if len(code) > 800 else ''}")

        if self._docker_available:
            return self._run_docker(code, file_bytes, filename, progress_cb)

        # SECURITY: subprocess fallback executes LLM-generated code on the host.
        # Only allowed when SANDBOX_ALLOW_SUBPROCESS=true (dev mode).
        if not settings.SANDBOX_ALLOW_SUBPROCESS:
            logger.error(
                "Sandbox: Docker unavailable and subprocess fallback is DISABLED "
                "(SANDBOX_ALLOW_SUBPROCESS=false). Set to true for local dev only."
            )
            return SandboxResult(
                success=False,
                stderr=(
                    "File analysis requires Docker in production. "
                    "Docker is not running. Please start Docker and try again."
                ),
            )

        logger.warning(
            "Sandbox: Docker unavailable — using subprocess fallback. "
            "Set SANDBOX_ALLOW_SUBPROCESS=false in production."
        )
        return self._run_subprocess(code, file_bytes, filename, progress_cb)

    # ── Docker ─────────────────────────────────────────────────────────────────

    def _run_docker(
        self,
        code: str,
        file_bytes: bytes | None,
        filename: str,
        progress_cb: Callable | None,
    ) -> SandboxResult:
        with tempfile.TemporaryDirectory(prefix="syslens_") as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "run.py").write_text(_HARNESS.format(user_code=_indent(code)))

            cmd = [
                "docker", "run", "--rm",
                "--network", "none",
                "--memory=512m",
                "--security-opt", "no-new-privileges",
                "--tmpfs", "/tmp:rw,size=64m",
                "--tmpfs", "/root:rw,size=16m",
                "-v", f"{tmpdir}:/sandbox:ro",
                "-w", "/sandbox",
            ]

            # FIX: inject SYSLENS_FILE with correct path inside container
            if file_bytes:
                (tmp / filename).write_bytes(file_bytes)
                cmd.extend(["-e", f"SYSLENS_FILE=/sandbox/{filename}"])
                logger.info(f"Sandbox (Docker): SYSLENS_FILE=/sandbox/{filename}")

            cmd.extend([settings.SANDBOX_IMAGE, "python", "/sandbox/run.py"])

            logger.info("Sandbox: starting Docker container")
            if progress_cb:
                progress_cb("Sandbox: starting Docker container")

            logger.debug(f"Docker cmd: {' '.join(cmd)}")

            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True,
                    timeout=settings.SANDBOX_TIMEOUT_SEC,
                )
            except subprocess.TimeoutExpired:
                logger.error(f"Sandbox: Docker timed out after {settings.SANDBOX_TIMEOUT_SEC}s")
                return SandboxResult(success=False, stderr=f"Timed out after {settings.SANDBOX_TIMEOUT_SEC}s")
            except FileNotFoundError:
                logger.warning("Sandbox: docker binary not found, switching to subprocess")
                self._docker_available = False
                return self._run_subprocess(code, file_bytes, filename, progress_cb)

            return self._parse_output(proc, progress_cb)

    # ── Subprocess fallback ────────────────────────────────────────────────────

    def _run_subprocess(
        self,
        code: str,
        file_bytes: bytes | None,
        filename: str,
        progress_cb: Callable | None,
    ) -> SandboxResult:
        with tempfile.TemporaryDirectory(prefix="syslens_") as tmpdir:
            tmp = Path(tmpdir)
            script = tmp / "run.py"
            harness = _HARNESS.format(user_code=_indent(code))
            script.write_text(harness)

            # FIX: inject SYSLENS_FILE with correct absolute host path
            env_vars = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
            if file_bytes:
                data_path = tmp / filename
                data_path.write_bytes(file_bytes)
                env_vars["SYSLENS_FILE"] = str(data_path)
                logger.info(
                    f"Sandbox (subprocess): SYSLENS_FILE={data_path} ({len(file_bytes)} bytes)"
                )

            logger.info(f"Sandbox: running subprocess with {sys.executable}")
            logger.debug(f"Sandbox: script path = {script}")
            if progress_cb:
                progress_cb(f"Sandbox: running with {Path(sys.executable).name}")

            try:
                proc = subprocess.run(
                    [sys.executable, str(script)],
                    capture_output=True, text=True,
                    timeout=settings.SANDBOX_TIMEOUT_SEC,
                    cwd=tmpdir,
                    env=env_vars,
                )
            except subprocess.TimeoutExpired:
                logger.error(f"Sandbox: subprocess timed out after {settings.SANDBOX_TIMEOUT_SEC}s")
                return SandboxResult(success=False, stderr=f"Timed out after {settings.SANDBOX_TIMEOUT_SEC}s")
            except Exception as e:
                logger.exception(f"Sandbox: subprocess launch failed — {e}")
                return SandboxResult(success=False, stderr=str(e))

            return self._parse_output(proc, progress_cb)

    # ── Output parsing ─────────────────────────────────────────────────────────

    def _parse_output(
        self,
        proc: subprocess.CompletedProcess,
        progress_cb: Callable | None,
    ) -> SandboxResult:
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""

        # Always log full output for debugging
        logger.info(f"Sandbox: exit_code={proc.returncode}")
        if stdout.strip():
            logger.debug(f"Sandbox STDOUT:\n{stdout[:2000]}")
        if stderr.strip():
            logger.warning(f"Sandbox STDERR:\n{stderr[:2000]}")

        if progress_cb:
            progress_cb(f"Sandbox: exit_code={proc.returncode}")

        if proc.returncode != 0:
            error_msg = stderr
            if "__ERROR_START__" in stderr:
                try:
                    err_data = json.loads(stderr.split("__ERROR_START__", 1)[-1].strip())
                    error_msg = err_data.get("error", stderr)
                except Exception:
                    error_msg = stderr

            logger.error(f"Sandbox FAILED:\n{error_msg}")
            return SandboxResult(
                success=False, stdout=stdout,
                stderr=error_msg[:1000], exit_code=proc.returncode,
            )

        if "__OUTPUT_START__" in stdout:
            json_text = stdout.split("__OUTPUT_START__", 1)[-1].strip()
            try:
                output_data = json.loads(json_text)
                logger.info("Sandbox: output parsed successfully")
                return SandboxResult(success=True, stdout=stdout, stderr=stderr, output_json=output_data)
            except json.JSONDecodeError as e:
                logger.error(f"Sandbox: JSON decode error — {e}\nRaw: {json_text[:400]}")
                return SandboxResult(success=False, stderr=f"JSON decode error: {e}\nOutput: {json_text[:300]}")

        logger.error("Sandbox: no __OUTPUT_START__ marker found in stdout")
        return SandboxResult(success=False, stderr="No __OUTPUT_START__ marker in stdout", stdout=stdout)

    # ── Docker check ───────────────────────────────────────────────────────────

    @staticmethod
    def _check_docker() -> bool:
        try:
            result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
            available = result.returncode == 0
            logger.debug(f"Docker check: returncode={result.returncode} available={available}")
            return available
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.debug("Docker check: binary not found or timed out")
            return False