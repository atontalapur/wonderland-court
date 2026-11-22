"""Check that Wonderland Court installs and runs with pipx on a clean machine.

    uv run python scripts/check_pipx_install.py
    uv run python scripts/check_pipx_install.py --spec git+https://github.com/atontalapur/wonderland-court

It builds the wheel and checks that the Courtroom UI and the store schema are inside it, then
installs it (or `--spec`) with pipx into a temporary PIPX_HOME and PIPX_BIN_DIR. pipx itself
runs through `uv tool run`, so nothing is installed globally. The installed `court` then runs
from an empty folder with a bare PATH, so it can't see this checkout or Node: --version,
--help, a mock trial, `court ci` over and within budget, and `court serve` replaying a run,
whose page and assets are fetched. The temporary folder is deleted afterwards unless --keep.

Needs only Python 3.11+ and uv, plus network access to PyPI.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPLAY = ROOT / "fixtures" / "fake_run.jsonl"
PACKAGE = "wonderland-court"
WHEEL_FILES = (
    "wonderland_court/courtroom/static/index.html",
    "wonderland_court/engine/schema.sql",
)
BARE_PATH = os.pathsep.join(["/usr/bin", "/bin"])


class CheckFailed(Exception):
    pass


def ok(message: str) -> None:
    print(f"ok    {message}", flush=True)


def run(
    args: Sequence[str | Path],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    expect: int = 0,
) -> str:
    proc = subprocess.run(
        [str(arg) for arg in args],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=600,
    )
    output = proc.stdout + proc.stderr
    if proc.returncode != expect:
        raise CheckFailed(
            f"`{' '.join(map(str, args))}` exited {proc.returncode}, expected {expect}:\n{output}"
        )
    return output


def build_wheel(out: Path) -> Path:
    run(["uv", "build", "--wheel", "--out-dir", out, ROOT])
    [wheel] = out.glob("*.whl")
    names = set(zipfile.ZipFile(wheel).namelist())
    missing = [name for name in WHEEL_FILES if name not in names]
    if missing:
        raise CheckFailed(f"{wheel.name} is missing {', '.join(missing)}")
    assets = [n for n in names if re.fullmatch(r"wonderland_court/courtroom/static/assets/.+", n)]
    if not assets:
        raise CheckFailed(f"{wheel.name} has no built Courtroom assets")
    ok(f"built {wheel.name} with {', '.join(WHEEL_FILES)} and {len(assets)} UI assets")
    return wheel


def pipx_install(spec: str, tmp: Path, python: str) -> tuple[Path, Path]:
    """Install `spec` into a pipx home under `tmp`. Returns the bin dir and the app's venv."""
    home, bin_dir = tmp / "pipx-home", tmp / "pipx-bin"
    env = {
        **os.environ,
        "PIPX_HOME": str(home),
        "PIPX_BIN_DIR": str(bin_dir),
        "PIPX_MAN_DIR": str(tmp / "pipx-man"),
        "PIP_CACHE_DIR": str(tmp / "pip-cache"),
    }
    for name in ("VIRTUAL_ENV", "PYTHONPATH", "PIPX_DEFAULT_PYTHON"):
        env.pop(name, None)
    run(["uv", "tool", "run", "--python", python, "pipx", "install", spec], env=env)
    if not (bin_dir / "court").exists():
        raise CheckFailed(f"pipx installed no `court` into {bin_dir}")
    ok(f"pipx installed {spec} into a temporary PIPX_HOME, on Python {python}")
    return bin_dir, home / "venvs" / PACKAGE


def check_installed_files(venv: Path) -> None:
    for name in WHEEL_FILES:
        if not list(venv.glob(f"lib/python*/site-packages/{name}")):
            raise CheckFailed(f"the installed package has no {name}")
    ok("the installed package has the Courtroom UI and the store schema")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as response:
        body: bytes = response.read()
        return body.decode("utf-8")


def check_serve(court: Path, env: dict[str, str], work: Path) -> None:
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    args = [str(court), "serve", "--replay", str(REPLAY), "--port", str(port), "--speed", "8"]
    with subprocess.Popen(
        args, env=env, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    ) as server:
        try:
            page = ""
            for _ in range(60):
                if server.poll() is not None:
                    output = server.stdout.read() if server.stdout else ""
                    raise CheckFailed(f"court serve exited {server.returncode}:\n{output}")
                try:
                    page = fetch(url + "/")
                    break
                except OSError:
                    time.sleep(0.5)
            if '<div id="root">' not in page:
                raise CheckFailed(f"court serve didn't serve the Courtroom page at {url}/")
            assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', page)
            for asset in assets:
                fetch(url + asset)
            ok(f"court serve --replay served the Courtroom page and {len(assets)} assets")
        finally:
            server.terminate()
            server.wait(timeout=10)


def check_court(bin_dir: Path, tmp: Path) -> None:
    """Run the installed `court` the way a fresh machine would: empty folder, bare PATH."""
    work, home = tmp / "work", tmp / "home"
    work.mkdir()
    home.mkdir()
    path = os.pathsep.join([str(bin_dir), BARE_PATH])
    env = {"PATH": path, "HOME": str(home), "LANG": "C.UTF-8", "COLUMNS": "120", "NO_COLOR": "1"}
    if shutil.which("node", path=path):
        raise CheckFailed("node is on the bare PATH, so the check can't show it isn't needed")
    court = bin_dir / "court"

    version = run([court, "--version"], env=env, cwd=work)
    ok(f"court --version: {version.strip()}")
    help_text = run([court, "--help"], env=env, cwd=work)
    if " ci " not in help_text:
        raise CheckFailed(f"court --help doesn't list ci:\n{help_text}")
    ok("court --help")
    trial = run([court, "trial", "--quick", "--mock", "--db", "trial.db"], env=env, cwd=work)
    if "matches leaked" not in trial:
        raise CheckFailed(f"the mock trial printed no result:\n{trial}")
    ok("court trial --quick --mock")
    ci = ["ci", "--quick", "--mock"]
    run([court, *ci, "--db", "ci.db", "--sarif-out", "court.sarif"], env=env, cwd=work, expect=1)
    sarif = json.loads((work / "court.sarif").read_text(encoding="utf-8"))
    if sarif.get("version") != "2.1.0" or not sarif["runs"][0]["results"]:
        raise CheckFailed("court ci wrote no SARIF findings")
    ok("court ci --quick --mock exits 1 over budget and writes SARIF")
    run([court, *ci, "--db", "ci-pass.db", "--fail-above", "1"], env=env, cwd=work)
    ok("court ci --quick --mock --fail-above 1 exits 0")
    check_serve(court, env, work)


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--spec",
        help="What pipx installs, such as a git+https URL. Defaults to a wheel built from here.",
    )
    parser.add_argument(
        "--python", default="3.11", help="Python for pipx and Court (default: 3.11, the oldest)."
    )
    parser.add_argument("--keep", action="store_true", help="Keep the temporary folder.")
    args = parser.parse_args()
    if shutil.which("uv") is None:
        sys.exit("uv isn't on PATH: https://docs.astral.sh/uv/getting-started/installation/")

    tmp = Path(tempfile.mkdtemp(prefix="court-pipx-check-"))
    try:
        spec = args.spec or str(build_wheel(tmp / "dist"))
        bin_dir, venv = pipx_install(spec, tmp, args.python)
        check_installed_files(venv)
        check_court(bin_dir, tmp)
    except CheckFailed as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        if args.keep:
            print(f"kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    print("Clean-machine pipx install works.")


if __name__ == "__main__":
    main()
