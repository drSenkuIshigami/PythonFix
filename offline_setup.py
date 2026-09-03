# -*- coding: utf-8 -*-
r"""
Offline / broken-pip setup for Windows PCs.

WHAT THIS SCRIPT DOES
  1. Uses the Python that launched it (normally chosen by run_setup.bat).
  2. Discovers other Python installs and switches to a better match if needed.
  3. Creates an isolated virtual environment in .local_env (no global pip).
  4. Puts third-party packages into the local deps\ folder as wheels.
  5. Installs those packages into .local_env from deps\ only (offline).
  6. Verifies that every required import works.
  7. Logs every step to setup_log.txt. No prompts.

HOW TO PREPARE A DISTRIBUTABLE FOLDER (on a PC that HAS internet)
  Double-click run_setup.bat  OR  from this folder run:
      py -3 -m pip download -r requirements.txt pip setuptools wheel -d deps
  Copy this whole folder (script, BAT, requirements.txt, and deps\) to other PCs.

ON A TARGET PC (pip broken, no internet, or both)
  Double-click run_setup.bat
  The BAT finds python.exe, then this script installs from deps\ into .local_env.

After a successful run:
  python / pip should work in a NEW Command Prompt or PowerShell
  (this script adds the real Python folder and Scripts\\pip.exe to PATH).
  Isolated interpreter: .local_env\\Scripts\\python.exe
  This session only:    call enable_pip.bat   or   . .\\enable_pip.ps1
"""

from __future__ import annotations

import ctypes
import glob as globmod
import os
import re
import socket
import struct
import subprocess
import sys
import winreg
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Layout (all paths are next to this script, not the current working directory)
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
DEPS_DIR = SCRIPT_DIR / "deps"
VENV_DIR = SCRIPT_DIR / ".local_env"
REQ_FILE = SCRIPT_DIR / "requirements.txt"
LOG_FILE = SCRIPT_DIR / "setup_log.txt"
GET_PIP = SCRIPT_DIR / "get-pip.py"

REQUIRED_PACKAGES = ["requests", "numpy"]
BOOTSTRAP_PACKAGES = ["pip", "setuptools", "wheel"]
MIN_PY = (3, 8)
REEXEC_ENV = "OFFLINE_SETUP_SELECTED"

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class SetupError(Exception):
    """Raised for a fatal, user-visible setup failure."""


def log(message: str, level: str = "INFO") -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} [{level}] {message}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def fail(message: str) -> None:
    log(message, "ERROR")
    raise SetupError(message)


def _base_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    if extra:
        env.update(extra)
    env["PYTHONUNBUFFERED"] = "1"
    env["PIP_NO_INPUT"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_PROGRESS_BAR"] = "off"
    return env


def run(
    args: list[str],
    *,
    timeout: int = 600,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and stream output into the log (avoids Windows pipe deadlocks)."""
    display = " ".join(args)
    log(f"RUN: {display}")
    merged = _base_env(env)
    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=merged,
            cwd=str(SCRIPT_DIR),
            bufsize=1,
        )
    except FileNotFoundError:
        fail(f"Executable not found: {args[0]}")

    collected: list[str] = []
    try:
        assert process.stdout is not None
        for line in process.stdout:
            text = line.rstrip("\r\n")
            if text:
                collected.append(text)
                log(f"  out: {text}")
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=30)
        fail(f"Command timed out after {timeout}s: {display}")

    stdout = "\n".join(collected)
    completed = subprocess.CompletedProcess(args, process.returncode or 0, stdout, "")
    if check and completed.returncode != 0:
        fail(f"Command failed (exit {completed.returncode}): {display}")
    return completed


def has_internet(timeout: float = 2.0) -> bool:
    """One cheap connectivity check. No other network calls unless this is True."""
    for host, port in (("8.8.8.8", 53), ("1.1.1.1", 53)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def probe_python(exe: Path) -> dict | None:
    if not exe.is_file():
        return None
    if "WindowsApps" in str(exe):
        return None
    code = (
        "import struct, sys; "
        "print(sys.version_info[0], sys.version_info[1], sys.version_info[2], "
        "struct.calcsize('P')*8, sys.executable, sep='|')"
    )
    try:
        completed = subprocess.run(
            [str(exe), "-c", code],
            timeout=15,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    parts = completed.stdout.strip().split("|")
    if len(parts) < 5:
        return None
    major, minor, patch, bits = (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
    if (major, minor) < MIN_PY:
        return None
    return {
        "exe": Path(parts[4]),
        "version": (major, minor, patch),
        "bits": bits,
        "tag": f"cp{major}{minor}",
    }


def _reg_pythons() -> list[Path]:
    found: list[Path] = []
    roots = [
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Python\PythonCore"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Python\PythonCore"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Python\ContinuumAnalytics"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Python\ContinuumAnalytics"),
    ]
    views = [winreg.KEY_READ | winreg.KEY_WOW64_64KEY, winreg.KEY_READ | winreg.KEY_WOW64_32KEY]
    for hive, base in roots:
        for view in views:
            try:
                with winreg.OpenKey(hive, base, 0, view) as core:
                    i = 0
                    while True:
                        try:
                            ver = winreg.EnumKey(core, i)
                        except OSError:
                            break
                        i += 1
                        try:
                            with winreg.OpenKey(hive, f"{base}\\{ver}\\InstallPath", 0, view) as ip:
                                try:
                                    exe, _ = winreg.QueryValueEx(ip, "ExecutablePath")
                                    found.append(Path(exe))
                                except OSError:
                                    install, _ = winreg.QueryValueEx(ip, "")
                                    found.append(Path(install) / "python.exe")
                        except OSError:
                            continue
            except OSError:
                continue
    return found


def _dir_pythons() -> list[Path]:
    local = os.environ.get("LOCALAPPDATA", "")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    patterns = [
        str(Path(local) / "Programs" / "Python" / "Python*" / "python.exe"),
        str(Path(local) / "Python" / "pythoncore-*" / "python.exe"),
        str(Path(pf) / "Python*" / "python.exe"),
        str(Path(pf86) / "Python*" / "python.exe"),
        r"C:\Python*\python.exe",
        str(Path.home() / "anaconda3" / "python.exe"),
        str(Path.home() / "miniconda3" / "python.exe"),
        str(Path(local) / "anaconda3" / "python.exe"),
        str(Path(local) / "miniconda3" / "python.exe"),
        str(Path(pf) / "PyManager" / "python.exe"),
    ]
    found: list[Path] = []
    for pattern in patterns:
        if "*" in pattern:
            found.extend(Path(match) for match in globmod.glob(pattern))
        else:
            path = Path(pattern)
            if path.is_file():
                found.append(path)
    return found


def discover_pythons() -> list[dict]:
    candidates: list[Path] = [Path(sys.executable)]
    for name in ("py", "python", "python3"):
        try:
            completed = subprocess.run(
                ["where", name],
                timeout=10,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
            )
            for line in completed.stdout.splitlines():
                path = line.strip()
                if path:
                    candidates.append(Path(path))
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        completed = subprocess.run(
            ["py", "-0p"],
            timeout=10,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        for line in completed.stdout.splitlines():
            match = re.search(r"([A-Za-z]:\\[^\s]+\.exe)", line, re.I)
            if match:
                candidates.append(Path(match.group(1)))
    except (OSError, subprocess.TimeoutExpired):
        pass
    candidates.extend(_reg_pythons())
    candidates.extend(_dir_pythons())

    seen: set[str] = set()
    results: list[dict] = []
    for exe in candidates:
        info = probe_python(exe)
        if not info:
            continue
        try:
            key = str(info["exe"].resolve()).lower()
        except OSError:
            key = str(info["exe"]).lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(info)
        log(
            f"Discovered Python {info['version'][0]}.{info['version'][1]}.{info['version'][2]} "
            f"{info['bits']}-bit  [{info['tag']}]  {info['exe']}"
        )
    if not results:
        fail("No usable Python 3.8+ interpreter was found.")
    return results


def wheel_tags_in_deps() -> set[str]:
    tags: set[str] = set()
    if not DEPS_DIR.is_dir():
        return tags
    for wheel in DEPS_DIR.glob("*.whl"):
        # name-ver-pytag-abitag-platform.whl
        parts = wheel.stem.split("-")
        if len(parts) >= 4:
            tags.add(parts[-3])  # cp311 / py3 / ...
    return tags


def select_python(installed: list[dict]) -> dict:
    native_bits = struct.calcsize("P") * 8
    tags = wheel_tags_in_deps()
    cp_tags = {t for t in tags if t.startswith("cp") and t[2:].isdigit()}

    ranked = list(installed)
    if cp_tags:
        matching = [p for p in ranked if p["tag"] in cp_tags]
        if matching:
            ranked = matching
            log(f"Preferring interpreters that match bundled wheel tags: {sorted(cp_tags)}")
    ranked.sort(
        key=lambda p: (
            p["bits"] == native_bits,
            p["version"],
        ),
        reverse=True,
    )
    chosen = ranked[0]
    log(
        f"Selected Python {chosen['version'][0]}.{chosen['version'][1]}.{chosen['version'][2]} "
        f"{chosen['bits']}-bit: {chosen['exe']}"
    )
    return chosen


def maybe_reexec(chosen: dict) -> None:
    if os.environ.get(REEXEC_ENV) == "1":
        return
    try:
        current = Path(sys.executable).resolve()
        target = Path(chosen["exe"]).resolve()
    except OSError:
        current, target = Path(sys.executable), Path(chosen["exe"])
    if current == target:
        return
    log(f"Re-launching with selected interpreter: {target}")
    env = os.environ.copy()
    env[REEXEC_ENV] = "1"
    completed = subprocess.run(
        [str(target), str(Path(__file__).resolve()), *sys.argv[1:]],
        env=env,
        cwd=str(SCRIPT_DIR),
    )
    sys.exit(completed.returncode)


def read_requirements() -> list[str]:
    names: list[str] = []
    if REQ_FILE.is_file():
        for line in REQ_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                names.append(re.split(r"[<>=!~\[]", stripped, maxsplit=1)[0].strip())
    return names or list(REQUIRED_PACKAGES)


def deps_has_packages(names: list[str]) -> bool:
    if not DEPS_DIR.is_dir():
        return False
    files = [p.name.lower() for p in DEPS_DIR.iterdir() if p.is_file()]
    if not files:
        return False
    for name in names:
        key = name.lower().replace("-", "_")
        if not any(key in f.replace("-", "_") and (f.endswith(".whl") or f.endswith(".tar.gz") or f.endswith(".zip")) for f in files):
            return False
    return True


def python_has_pip(exe: Path) -> bool:
    completed = run([str(exe), "-m", "pip", "--version"], check=False, timeout=60)
    return completed.returncode == 0


def bootstrap_pip(exe: Path, online: bool) -> None:
    if python_has_pip(exe):
        log(f"pip is available in {exe}")
        return

    log("pip missing; trying ensurepip (no network)")
    ensure = run([str(exe), "-m", "ensurepip", "--upgrade", "--default-pip"], check=False, timeout=180)
    if ensure.returncode == 0 and python_has_pip(exe):
        log("pip bootstrapped with ensurepip")
        return

    if GET_PIP.is_file():
        log("Trying bundled get-pip.py")
        args = [str(exe), str(GET_PIP)]
        if DEPS_DIR.is_dir() and any(DEPS_DIR.iterdir()):
            args += ["--no-index", "--find-links", str(DEPS_DIR)]
        gp = run(args, check=False, timeout=300)
        if gp.returncode == 0 and python_has_pip(exe):
            log("pip bootstrapped with bundled get-pip.py")
            return

    if online:
        log("Downloading get-pip.py (internet is available)")
        import urllib.request

        url = "https://bootstrap.pypa.io/get-pip.py"
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                GET_PIP.write_bytes(resp.read())
        except Exception as exc:  # noqa: BLE001 - surface any download failure
            fail(f"Could not download get-pip.py: {exc}")
        gp = run([str(exe), str(GET_PIP)], check=False, timeout=300)
        if gp.returncode == 0 and python_has_pip(exe):
            log("pip bootstrapped with downloaded get-pip.py")
            return

    fail(
        "Could not bootstrap pip. Place get-pip.py next to this script, "
        "or copy a deps\\ folder that includes pip wheels, then re-run."
    )


def populate_deps(exe: Path, online: bool, names: list[str]) -> None:
    DEPS_DIR.mkdir(parents=True, exist_ok=True)
    if deps_has_packages(names) and deps_has_packages(["pip"]):
        log(f"deps folder already has required packages: {DEPS_DIR}")
        return
    if not online:
        if deps_has_packages(names):
            log("No internet; using existing deps folder")
            return
        fail(
            "The deps folder is empty or incomplete, and this PC has no internet. "
            "On a PC with internet, run run_setup.bat once (or: "
            "python -m pip download -r requirements.txt pip setuptools wheel -d deps) "
            "and copy the deps folder with this script."
        )

    log(f"Downloading packages into {DEPS_DIR}")
    cmd = [
        str(exe),
        "-m",
        "pip",
        "download",
        "--no-input",
        "--progress-bar",
        "off",
        "-d",
        str(DEPS_DIR),
        *BOOTSTRAP_PACKAGES,
    ]
    if REQ_FILE.is_file():
        cmd += ["-r", str(REQ_FILE)]
    else:
        cmd += names
    run(cmd, timeout=1200)
    log("Package download finished")


def create_venv(base_python: Path) -> Path:
    venv_py = VENV_DIR / "Scripts" / "python.exe"
    need_create = not venv_py.is_file()
    marker = VENV_DIR / ".base_python"
    if venv_py.is_file() and marker.is_file():
        if marker.read_text(encoding="utf-8").strip().lower() != str(base_python).lower():
            log("Existing venv was built with a different Python; recreating")
            need_create = True
    if need_create:
        log(f"Creating virtual environment at {VENV_DIR}")
        args = [str(base_python), "-m", "venv", str(VENV_DIR)]
        if VENV_DIR.exists():
            args = [str(base_python), "-m", "venv", "--clear", str(VENV_DIR)]
        created = run(args, check=False, timeout=180)
        if created.returncode != 0 or not venv_py.is_file():
            fail(
                "Could not create a venv. This Python may be missing the venv module. "
                "Repair the Python install (include 'pip' / 'venv') and re-run."
            )
        marker.write_text(str(base_python), encoding="utf-8")
    else:
        log(f"Reusing virtual environment at {VENV_DIR}")
    return venv_py


def venv_environ() -> dict[str, str]:
    env = os.environ.copy()
    scripts = str(VENV_DIR / "Scripts")
    env["VIRTUAL_ENV"] = str(VENV_DIR)
    env["PATH"] = scripts + os.pathsep + env.get("PATH", "")
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    return env


def install_from_deps(venv_py: Path, online: bool) -> None:
    if not DEPS_DIR.is_dir() or not any(DEPS_DIR.iterdir()):
        fail(f"deps folder is missing or empty: {DEPS_DIR}")

    log("Installing packages from local deps folder (no index / no network)")
    cmd = [
        str(venv_py),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
        str(DEPS_DIR),
        "--upgrade",
        "--no-input",
        "--progress-bar",
        "off",
        "--disable-pip-version-check",
    ]
    if REQ_FILE.is_file():
        cmd += ["-r", str(REQ_FILE)]
    else:
        cmd += REQUIRED_PACKAGES
    installed = run(cmd, timeout=1200, check=False, env=venv_environ())
    if installed.returncode != 0:
        hint = ""
        if online:
            hint = (
                " Wheels in deps may not match this Python version. "
                "Delete deps\\ and re-run on this PC so wheels are downloaded for it."
            )
        else:
            hint = (
                " Rebuild deps on a PC with the same Python version "
                f"({sys.version_info.major}.{sys.version_info.minor}) and the same 32/64-bit."
            )
        fail("Install from deps failed." + hint)


def verify_imports(venv_py: Path, names: list[str]) -> None:
    log(f"Verifying imports: {', '.join(names)}")
    code = (
        "import importlib, sys;\n"
        + "".join(
            f"m = importlib.import_module({name!r}); "
            f"print({name!r}, getattr(m, '__version__', 'ok'))\n"
            for name in names
        )
    )
    completed = run([str(venv_py), "-c", code], timeout=120, check=False, env=venv_environ())
    if completed.returncode != 0:
        fail(
            "Installed packages but import verification failed. "
            "A wheel may need a missing Visual C++ runtime, or deps do not match this Python."
        )
    log("All required imports succeeded")


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def _norm_path_entry(entry: str) -> str:
    return os.path.normcase(os.path.normpath(entry.strip().strip('"')))


def _read_registry_path(hive: int, key: str) -> tuple[str, int]:
    try:
        with winreg.OpenKey(hive, key, 0, winreg.KEY_READ) as handle:
            value, typ = winreg.QueryValueEx(handle, "Path")
            return str(value or ""), typ
    except OSError:
        return "", winreg.REG_EXPAND_SZ


def _write_registry_path(hive: int, key: str, value: str, typ: int) -> None:
    access = winreg.KEY_READ | winreg.KEY_SET_VALUE
    with winreg.OpenKey(hive, key, 0, access) as handle:
        winreg.SetValueEx(handle, "Path", 0, typ, value)


def _prepend_to_path_value(current: str, additions: list[Path]) -> tuple[str, list[str]]:
    parts = [p for p in current.split(";") if p.strip()]
    existing = {_norm_path_entry(p) for p in parts}
    added: list[str] = []
    prefix: list[str] = []
    for item in additions:
        text = str(item)
        if not item.is_dir():
            log(f"Skip PATH (folder missing): {text}")
            continue
        key = _norm_path_entry(text)
        if key in existing or key in {_norm_path_entry(p) for p in prefix}:
            log(f"Already on PATH: {text}")
            continue
        prefix.append(text)
        added.append(text)
    if not prefix:
        return current, added
    return ";".join(prefix + parts), added


def broadcast_environment_change() -> None:
    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x001A
    SMTO_ABORTIFHUNG = 0x0002
    result = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(
        HWND_BROADCAST,
        WM_SETTINGCHANGE,
        0,
        ctypes.c_wchar_p("Environment"),
        SMTO_ABORTIFHUNG,
        5000,
        ctypes.byref(result),
    )


def write_path_helpers(python_dir: Path, python_scripts: Path, venv_scripts: Path) -> None:
    bat = SCRIPT_DIR / "enable_pip.bat"
    ps1 = SCRIPT_DIR / "enable_pip.ps1"
    bat.write_text(
        "\r\n".join(
            [
                "@echo off",
                "REM Adds python.exe and pip.exe to PATH for THIS Command Prompt only.",
                "REM For a permanent fix, run run_setup.bat (as Administrator if you can), then open a new terminal.",
                f'set "PATH={python_scripts};{python_dir};{venv_scripts};%PATH%"',
                "echo PATH updated in this window. Try:  python --version  and  pip --version",
                "",
            ]
        ),
        encoding="utf-8",
    )
    ps1.write_text(
        "\n".join(
            [
                "# Adds python.exe and pip.exe to PATH for THIS PowerShell window only.",
                "# Run:  . .\\enable_pip.ps1",
                "# For a permanent fix, run run_setup.bat, then open a new terminal.",
                f'$env:Path = "{python_scripts};{python_dir};{venv_scripts};" + $env:Path',
                'Write-Host "PATH updated in this window. Try: python --version   pip --version"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    log(f"Wrote session helpers: {bat.name}, {ps1.name}")


def ensure_pip_launcher(exe: Path) -> Path | None:
    """Make sure Scripts\\pip.exe exists. python -m pip can work without it."""
    scripts = exe.parent / "Scripts"
    pip_exe = scripts / "pip.exe"
    if pip_exe.is_file():
        log(f"pip.exe already exists: {pip_exe}")
        return pip_exe

    log("pip module is present but pip.exe is missing; creating the launcher")
    run([str(exe), "-m", "ensurepip", "--upgrade", "--default-pip"], check=False, timeout=180)
    if pip_exe.is_file():
        log(f"Created pip.exe with ensurepip: {pip_exe}")
        return pip_exe

    install_cmd = [str(exe), "-m", "pip", "install", "--upgrade", "--force-reinstall", "pip"]
    if DEPS_DIR.is_dir() and any(DEPS_DIR.glob("pip-*.whl")):
        install_cmd[4:4] = ["--no-index", "--find-links", str(DEPS_DIR)]
    run(install_cmd, check=False, timeout=300)
    if pip_exe.is_file():
        log(f"Created pip.exe with pip install: {pip_exe}")
        return pip_exe

    log(f"Could not create {pip_exe}; PATH will fall back to .local_env\\Scripts\\pip.exe", "ERROR")
    return None


def register_pip_on_path(base_python: Path, venv_py: Path) -> list[str]:
    python_dir = base_python.parent
    python_scripts = python_dir / "Scripts"
    venv_scripts = venv_py.parent
    write_path_helpers(python_dir, python_scripts, venv_scripts)

    ensure_pip_launcher(base_python)

    pip_exe = python_scripts / "pip.exe"
    if not pip_exe.is_file():
        log(f"pip.exe not in {python_scripts}; also adding venv Scripts so the pip command still works")

    # Real python.exe first; Scripts\\pip.exe next; venv Scripts as fallback pip.exe.
    additions = [python_scripts, python_dir, venv_scripts]
    targets: list[tuple[str, int, str]] = [
        ("User", winreg.HKEY_CURRENT_USER, r"Environment"),
    ]
    if is_admin():
        targets.append(
            (
                "System",
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
            )
        )
        log("Running as Administrator: will add python/pip to the system PATH")
    else:
        log("Not elevated: will add python/pip to this user's PATH only")

    added_all: list[str] = []
    for label, hive, key in targets:
        current, typ = _read_registry_path(hive, key)
        if typ not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
            typ = winreg.REG_EXPAND_SZ
        updated, added = _prepend_to_path_value(current, additions)
        if not added:
            log(f"{label} PATH already contains Python/Scripts")
            continue
        try:
            _write_registry_path(hive, key, updated, typ)
        except OSError as exc:
            log(f"Could not write {label} PATH: {exc}", "ERROR")
            if label == "System":
                log("Re-run run_setup.bat as Administrator to add pip for all users")
            continue
        added_all.extend(added)
        log(f"Updated {label} PATH with: {'; '.join(added)}")

    os.environ["PATH"] = (
        str(python_scripts)
        + os.pathsep
        + str(python_dir)
        + os.pathsep
        + str(venv_scripts)
        + os.pathsep
        + os.environ.get("PATH", "")
    )
    broadcast_environment_change()
    return added_all


def main() -> int:
    try:
        if LOG_FILE.exists() and os.environ.get(REEXEC_ENV) != "1":
            # Keep prior runs; just add a separator.
            log("-" * 72)
        log("=== Offline setup starting ===")
        log(f"Launcher Python: {sys.executable} ({sys.version.replace(chr(10), ' ')})")
        log(f"Script directory: {SCRIPT_DIR}")

        if not REQ_FILE.is_file():
            REQ_FILE.write_text("\n".join(REQUIRED_PACKAGES) + "\n", encoding="utf-8")
            log(f"Wrote example {REQ_FILE.name}")

        online = has_internet()
        log("Internet: " + ("available" if online else "not available (offline mode, no network calls)"))

        installed = discover_pythons()
        chosen = select_python(installed)
        maybe_reexec(chosen)
        base = Path(chosen["exe"])

        names = read_requirements()
        log(f"Required packages: {', '.join(names)}")

        bootstrap_pip(base, online=online)
        populate_deps(base, online=online, names=names)

        venv_py = create_venv(base)
        bootstrap_pip(venv_py, online=False)
        install_from_deps(venv_py, online=online)
        verify_imports(venv_py, names)
        added = register_pip_on_path(base, venv_py)

        log("=== Setup complete ===")
        log(f"Use this interpreter: {venv_py}")
        python_dir = base.parent
        python_scripts = python_dir / "Scripts"
        print()
        print("SUCCESS. Isolated environment is ready.")
        print(f"  Python: {venv_py}")
        print(f"  Packages: {DEPS_DIR}")
        print(f"  Log: {LOG_FILE}")
        print()
        if added:
            print("Added to PATH so python and pip work in new terminals:")
            for item in added:
                print(f"  {item}")
        else:
            print("Python/Scripts were already on PATH (or PATH could not be written).")
        print()
        print("pip is NOT available in terminals that were already open.")
        print("Open a NEW Command Prompt or PowerShell, then run:  pip --version")
        print()
        print("In THIS window, either:")
        print(f'  "{python_scripts / "pip.exe"}" install -r requirements.txt')
        print(f'  "{base}" -m pip install -r requirements.txt')
        print("  .\\enable_pip.ps1          (PowerShell)   then   pip --version")
        print("  call enable_pip.bat       (cmd)           then   pip --version")
        return 0
    except SetupError as exc:
        print()
        print(f"FAILED: {exc}")
        print(f"See log: {LOG_FILE}")
        return 1
    except Exception as exc:  # noqa: BLE001
        log(f"Unexpected error: {type(exc).__name__}: {exc}", "ERROR")
        print()
        print(f"FAILED: unexpected error: {exc}")
        print(f"See log: {LOG_FILE}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
