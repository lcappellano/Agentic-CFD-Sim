"""Mesh check and solver execution for a built two-region case.

A zero exit code means the solver ran; convergence is judged by run_bounded.
"""
import argparse
import json
import math
from pathlib import Path
import re

from src.foam.environment import run_tool
from src.foam.hashing import digest

FIXED_FILES = [
    'settings.json', 'basis.json', 'constant/g', 'constant/regionProperties',
    *[f'constant/{r}/polyMesh/{n}' for r in ('fluid', 'solid') for n in ('points', 'faces', 'owner', 'neighbour', 'boundary', 'cellZones')],
    *[f'constant/{r}/{n}' for r in ('fluid', 'solid') for n in ('thermophysicalProperties', 'turbulenceProperties', 'radiationProperties')],
    *[f'system/{r}/{n}' for r in ('fluid', 'solid') for n in ('fvSchemes', 'fvSolution')],
]


def update_manifest(case, **values):
    path = Path(case) / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest.update(values)
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def check_mesh(case):
    for region in ('fluid', 'solid'):
        log = case / f'log.checkMesh.{region}'
        run_tool(['checkMesh', '-case', str(case), '-region', region], case, log)
        if 'Mesh OK.' not in log.read_text():
            raise RuntimeError(f'{region} mesh failed checkMesh; see {log}')


def decompose(case, ranks, resume):
    text = f'FoamFile {{ version 2.0; format ascii; class dictionary; object decomposeParDict; }}\nnumberOfSubdomains {ranks}; method scotch;\n'
    (case / 'system/decomposeParDict').write_text(text)
    for region in ('fluid', 'solid'):
        (case / f'system/{region}/decomposeParDict').write_text(text)
    if not resume:
        run_tool(['decomposePar', '-case', str(case), '-allRegions'], case, case / 'log.decomposePar')
    elif len(list(case.glob('processor[0-9]*'))) != ranks:
        raise ValueError('Resume requires the same decomposition rank count')


def run(case, ranks=1, check_only=False, resume=False, end_iteration=None):
    case = Path(case).resolve()
    if ranks < 1:
        raise ValueError('ranks must be positive')
    check_mesh(case)
    if check_only:
        return None
    if end_iteration is not None:
        if end_iteration <= 0:
            raise ValueError('end_iteration must be positive')
        control = case / 'system/controlDict'
        text = re.sub(r'endTime\s+[^;]+;', f'endTime {end_iteration};', control.read_text())
        # Fields must exist at the chunk end: keep the configured interval when it divides the end.
        interval = json.loads((case / 'settings.json').read_text()).get('write_interval', 100)
        text = re.sub(r'writeInterval\s+\d+;\s*purgeWrite', f'writeInterval {math.gcd(int(interval), int(end_iteration))}; purgeWrite', text, count=1)
        control.write_text(text)
    if (case / 'log.solver').exists() and not resume:
        raise ValueError('Existing solver log: use resume=True or a fresh case')
    command = ['chtMultiRegionSimpleFoam', '-case', str(case)]
    if ranks > 1:
        decompose(case, ranks, resume)
        command = ['mpirun', '--bind-to', 'none', '-np', str(ranks)] + command + ['-parallel']
    log_path = case / 'log.solver'
    if resume:
        index = 1
        while (case / f'log.solver.resume-{index}').exists():
            index += 1
        log_path = case / f'log.solver.resume-{index}'
    manifest = update_manifest(case, simulation_executed=True, execution_status='running', solver_command=command,
                               runner_sha256=digest(Path(__file__)))
    result = run_tool(command, case, log_path, check=False)
    logs = manifest.get('solver_logs', []) + [log_path.name]
    update_manifest(case, solver_logs=logs, execution_status='succeeded' if result.returncode == 0 else 'failed',
                    solver_exit_code=result.returncode)
    if result.returncode != 0:
        raise RuntimeError(f'Solver exited with {result.returncode}; see {log_path}')
    if ranks > 1:
        run_tool(['reconstructPar', '-case', str(case), '-allRegions', '-latestTime'], case, case / 'log.reconstructPar')
    update_manifest(case, fixed_input_sha256={name: digest(case / name) for name in FIXED_FILES if (case / name).is_file()})
    return log_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    parser.add_argument('--ranks', type=int, default=1)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--end-iteration', type=int)
    args = parser.parse_args()
    run(args.case, args.ranks, args.check_only, args.resume, args.end_iteration)


if __name__ == '__main__':
    main()
