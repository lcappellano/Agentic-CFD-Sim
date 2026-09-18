"""Locate and source the installed OpenFOAM environment; run its tools.

Callers never need ``bash -c "source .../bashrc && ..."`` wrappers: every
solver/utility runs through :func:`run_tool`, which sources the environment
once per process and records the version in ``openfoam_version()``.
"""
import functools
import os
from pathlib import Path
import shutil
import subprocess

CANDIDATES = ['/usr/lib/openfoam/openfoam2412/etc/bashrc', '/opt/openfoam2412/etc/bashrc']


def find_bashrc():
    explicit = os.environ.get('OPENFOAM_BASHRC')
    if explicit:
        return Path(explicit)
    if os.environ.get('WM_PROJECT_DIR'):
        return None  # Already sourced in this shell.
    for candidate in CANDIDATES:
        if Path(candidate).is_file():
            return Path(candidate)
    for candidate in sorted(Path('/usr/lib/openfoam').glob('openfoam*/etc/bashrc'), reverse=True):
        return candidate
    return None


@functools.lru_cache(maxsize=None)
def openfoam_env():
    """Environment dict with OpenFOAM sourced, or the current environment."""
    bashrc = find_bashrc()
    if bashrc is None:
        return dict(os.environ)
    output = subprocess.run(['bash', '-c', f'source "{bashrc}" >/dev/null 2>&1; env -0'],
                            capture_output=True, check=True).stdout
    env = {}
    for item in output.split(b'\0'):
        if b'=' in item:
            key, value = item.split(b'=', 1)
            env[key.decode(errors='replace')] = value.decode(errors='replace')
    return env


def openfoam_version():
    env = openfoam_env()
    return env.get('WM_PROJECT_VERSION')


def tool_available(name):
    env = openfoam_env()
    return shutil.which(name, path=env.get('PATH')) is not None


def run_tool(command, cwd, log_path, check=True, timeout=None):
    """Run an OpenFOAM tool with output captured to ``log_path``."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('w') as log:
        result = subprocess.run([str(c) for c in command], cwd=str(cwd), stdout=log,
                                stderr=subprocess.STDOUT, env=openfoam_env(), timeout=timeout)
    if check and result.returncode != 0:
        raise RuntimeError(f'{command[0]} failed with exit code {result.returncode}; see {log_path}')
    return result
