# Python Fix

**pip broken. Store stub on PATH. No internet. Still ship Python.**

Offline Windows bootstrap for Python, pip, and a local virtual environment — from **[Senku Ishigami](https://github.com/drSenkuIshigami)** ([@drSenkuIshigami](https://github.com/drSenkuIshigami)).

[![GitHub](https://img.shields.io/badge/GitHub-drSenkuIshigami-181717?logo=github)](https://github.com/drSenkuIshigami)
[![Follow](https://img.shields.io/github/followers/drSenkuIshigami?label=Follow&style=social)](https://github.com/drSenkuIshigami)
[![Stars](https://img.shields.io/github/stars/drSenkuIshigami/PythonFix?style=social)](https://github.com/drSenkuIshigami/PythonFix)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/drSenkuIshigami/PythonFix/pulls)

**Free to use. Free to reuse. Free to fork.** MIT — copy it, ship it, improve it, sell a product on top of it. Then come back and [star the repo](https://github.com/drSenkuIshigami/PythonFix), [follow @drSenkuIshigami](https://github.com/drSenkuIshigami), and [open a pull request](https://github.com/drSenkuIshigami/PythonFix/pulls). This project is built to be joined.

Also from this account: **[EbaratNeshan](https://github.com/drSenkuIshigami/EbaratNeshan)** — offline PDF & Word → Markdown. Recovers real Persian/Arabic letters from broken Word PDFs. RTL + LTR. LLM-ready. Nothing uploaded.

---

Use this folder when `pip` is missing or broken, the Microsoft Store Python stub is on PATH, or the PC has no internet. Double-click `run_setup.bat`. The script finds a real Python 3.8+ install, downloads wheels when the network is available, then installs everything from `deps\` into `.local_env` with no index and no further network calls.

## How it works

1. `run_setup.bat` locates a real `python.exe` (skips `WindowsApps` Store aliases).
2. `offline_setup.py` may switch to a better matching interpreter (version and 32/64-bit vs wheels in `deps\`).
3. pip is bootstrapped with `ensurepip`, a bundled `get-pip.py`, or a download if the PC is online.
4. Required packages are stored as wheels in `deps\`.
5. An isolated venv is created at `.local_env`.
6. Packages are installed from `deps\` only (`pip install --no-index --find-links`).
7. Imports are verified, then Python/Scripts are prepended on the user PATH (system PATH if you ran as Administrator).

There are no prompts. Every step is appended to `setup_log.txt`.

## Requirements

- Windows
- Python 3.8 or later already installed from [python.org](https://www.python.org/downloads/), Anaconda/Miniconda, or another real install
- During Python setup, enable **Add python.exe to PATH** and the **py launcher** when you can

Wheels currently in `deps\` were built for **64-bit Python 3.14** (`cp314`, `win_amd64`). On a PC with a different Python version or architecture, delete `deps\` and run setup once while online so matching wheels are downloaded.

## Usage

### On a PC with internet (prepare the folder)

Double-click `run_setup.bat`, or from this folder:

```bat
py -3 -m pip download -r requirements.txt pip setuptools wheel -d deps
```

Copy the whole folder (`offline_setup.py`, `run_setup.bat`, `requirements.txt`, and `deps\`) to target PCs.

### On a target PC (pip broken, offline, or both)

Double-click `run_setup.bat`.

After success, **open a new** Command Prompt or PowerShell (PATH changes do not apply to windows that were already open):

```bat
python --version
pip --version
```

Isolated interpreter:

```bat
.local_env\Scripts\python.exe
```

Same window only (no new terminal):

```bat
call enable_pip.bat
```

```powershell
. .\enable_pip.ps1
```

## Packages

Edit `requirements.txt` before the first download. Pin versions in production so every PC gets the same wheels.

Default example set:

- `requests`
- `numpy`

`pip`, `setuptools`, and `wheel` are always downloaded into `deps\` as well.

## Layout

| Path | Role |
|------|------|
| `run_setup.bat` | Finds a real Python and launches the setup script |
| `offline_setup.py` | Discovery, pip bootstrap, venv, offline install, PATH |
| `requirements.txt` | Packages to download and install |
| `deps\` | Local wheel cache (offline install source) |
| `.local_env\` | Isolated virtual environment (created on the target PC) |
| `setup_log.txt` | Full run log |
| `enable_pip.bat` / `enable_pip.ps1` | Session-only PATH helpers (rewritten each run) |

Optional: place `get-pip.py` next to the script if you need to bootstrap pip with no network and no `ensurepip`.

## Troubleshooting

| Problem | What to do |
|---------|------------|
| No Python found | Install Python 3.8+ from python.org. Avoid relying on the Microsoft Store alias. |
| Install from `deps\` fails | Wheels do not match this Python. Delete `deps\` and re-run online, or rebuild `deps\` on a PC with the same version and 32/64-bit. |
| `pip` works in a new terminal but not this one | PATH was updated in the registry, not in already-open windows. Open a new terminal, or run `enable_pip.bat` / `. .\enable_pip.ps1`. |
| Need PATH for all users | Re-run `run_setup.bat` as Administrator. |
| Import verification fails | A wheel may need the Visual C++ runtime, or `deps\` does not match this interpreter. See `setup_log.txt`. |

## Join this project

Python Fix is MIT. You do not need permission to use it, copy it, change it, or ship it.

- **Star** this repo so other Windows labs can find it: [drSenkuIshigami/PythonFix](https://github.com/drSenkuIshigami/PythonFix)
- **Follow** [Senku Ishigami · @drSenkuIshigami](https://github.com/drSenkuIshigami) for the next offline tools
- **Fork** and send a [pull request](https://github.com/drSenkuIshigami/PythonFix/pulls) — wheels for more Python versions, better discovery, docs, translations
- **Issues** with a log snippet (no secrets): [open one](https://github.com/drSenkuIshigami/PythonFix/issues)
- More from the same lab: [EbaratNeshan](https://github.com/drSenkuIshigami/EbaratNeshan)

License: [MIT](LICENSE) — free to use and reuse.

---

**10,000,000,000%**

### Ten billion percent: every impossible system is just an unsolved problem.

Senku Ishigami · drSenkuIshigami
