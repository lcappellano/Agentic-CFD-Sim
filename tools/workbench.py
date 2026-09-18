#!/usr/bin/env python3
"""Project command line: simulate a spec, inspect run state, record ad-hoc jobs."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.foam.hashing import digest  # noqa: E402
from src.foam.lock import compute_lock  # noqa: E402


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def local_path(value):
    path = (ROOT / value).resolve()
    path.relative_to(ROOT)
    return path


def doctor():
    from src.foam.environment import openfoam_env, find_bashrc
    env = openfoam_env()
    executables = ['git', 'python3', 'gmsh', 'checkMesh', 'chtMultiRegionSimpleFoam', 'potentialFoam',
                   'gmshToFoam', 'splitMeshRegions', 'decomposePar', 'mpirun', 'paraview']
    result = {'platform': platform.platform(), 'python': sys.version.split()[0], 'project_root': str(ROOT),
              'logical_cpus': os.cpu_count(), 'openfoam_bashrc': str(find_bashrc()),
              'openfoam_version': env.get('WM_PROJECT_VERSION'),
              'executables': {x: shutil.which(x, path=env.get('PATH')) for x in executables}}
    try:
        from src.cad.step_preview import backend
        gmsh = backend()
        gmsh.initialize()
        result['gmsh_runtime'] = gmsh.option.getString('General.Version')
        gmsh.finalize()
    except Exception as error:  # noqa: BLE001
        result['gmsh_runtime'] = f'unavailable: {error}'
    print(json.dumps(result, indent=2))


def stop_group(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def job_lock():
    return compute_lock(ROOT)


def run_job(args):
    """Record an arbitrary command with input hashes, log and exit status."""
    command = args.command[1:] if args.command and args.command[0] == '--' else args.command
    if not command:
        raise ValueError('Supply a command after --.')
    if args.timeout <= 0 or not math.isfinite(args.timeout):
        raise ValueError('Timeout must be a finite positive number of seconds.')
    cwd = local_path(args.cwd)
    if not cwd.is_dir():
        raise ValueError('Working directory does not exist.')
    inputs = [{'path': str(local_path(v).relative_to(ROOT)), 'sha256': digest(local_path(v))} for v in args.input]
    label = re.sub('[^a-zA-Z0-9_-]', '-', args.label)[:48] or 'job'
    from src.foam.environment import openfoam_env
    with job_lock():
        folder = ROOT / 'runs' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + label + '-' + uuid.uuid4().hex[:8])
        folder.mkdir()
        record = {'schema_version': 1, 'status': 'running', 'started_at': now(), 'command': command,
                  'cwd': str(cwd.relative_to(ROOT)), 'inputs': inputs, 'timeout_seconds': args.timeout,
                  'python': sys.version.split()[0], 'numerically_verified': False}
        save(folder / 'job.json', record)
        print(f'Job: {folder.relative_to(ROOT)}', flush=True)
        started = time.monotonic()
        process = None
        try:
            with (folder / 'console.log').open('w') as log:
                process = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                           start_new_session=True, env=openfoam_env())
                record['pid'] = process.pid
                save(folder / 'job.json', record)
                code = process.wait(timeout=args.timeout)
                record.update(exit_code=code, status='succeeded' if code == 0 else 'failed')
        except subprocess.TimeoutExpired:
            stop_group(process)
            record.update(status='timed_out', exit_code=process.returncode)
        except KeyboardInterrupt:
            if process is not None:
                stop_group(process)
            record.update(status='cancelled', exit_code=process.returncode if process else None)
        except OSError as error:
            record.update(status='failed', error=str(error), exit_code=None)
        finally:
            record.update(finished_at=now(), elapsed_seconds=round(time.monotonic() - started, 3))
            save(folder / 'job.json', record)
        print(json.dumps(record, indent=2))
        return 0 if record['status'] == 'succeeded' else 1


def run_tests(args):
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / 'src'), pattern=args.pattern, top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('doctor', help='Report the local toolchain.')
    simulate = sub.add_parser('simulate', help='Run a simulation spec end to end (cached per stage).')
    simulate.add_argument('spec')
    simulate.add_argument('--run', help='Existing run directory to continue; default creates a new one.')
    simulate.add_argument('--until', choices=['handoff', 'geometry', 'mesh', 'materials', 'screen', 'case', 'solve', 'audit', 'export'],
                          help='Stop after this stage.')
    simulate.add_argument('--dry-run', action='store_true', help='Print the resolved spec and exit.')
    status = sub.add_parser('status', help='Compact state of a run.')
    status.add_argument('run_directory')
    status.add_argument('--json', action='store_true')
    tests = sub.add_parser('test', help='Run the unit tests (set WORKBENCH_E2E=1 to include the solver fixture).')
    tests.add_argument('--pattern', default='test_*.py')
    review_import = sub.add_parser('review-import', help='Import STEP into a visual requirements review.')
    review_import.add_argument('--step', required=True)
    review_import.add_argument('--project', default='project.json')
    review_import.add_argument('--label', default='requirements')
    review_serve = sub.add_parser('review-serve', help='Serve the loopback 3D requirements review.')
    review_serve.add_argument('review_directory')
    review_serve.add_argument('--port', type=int, default=8765)
    for action in ('review-status', 'review-handoff', 'review-verify'):
        command = sub.add_parser(action)
        command.add_argument('review_directory')
    review_draft = sub.add_parser('review-draft', help='Save proposed selections/requirements; cannot approve.')
    review_draft.add_argument('review_directory')
    review_draft.add_argument('--draft', required=True)
    review_draft.add_argument('--revision', type=int, required=True)
    results_export = sub.add_parser('results-export', help='Export a stopped case for the 3D viewer.')
    results_export.add_argument('run_directory')
    results_export.add_argument('--case', required=True)
    results_export.add_argument('--time', required=True)
    results_export.add_argument('--output', required=True)
    results_serve = sub.add_parser('results-serve', help='Serve the read-only 3D results viewer.')
    results_serve.add_argument('export_directory')
    results_serve.add_argument('--run', help='Run directory (default: two levels above the export).')
    results_serve.add_argument('--port', type=int, default=8766)
    for action in ('check', 'prepare'):
        command = sub.add_parser(action, help='Legacy project.json intake helpers.')
        command.add_argument('--project', default='project.json')
        if action == 'prepare':
            command.add_argument('--label', default='request')
    job = sub.add_parser('job', help='Record an arbitrary command (OpenFOAM environment sourced).')
    job.add_argument('--label', default='job')
    job.add_argument('--cwd', default='.')
    job.add_argument('--input', action='append', default=[])
    job.add_argument('--timeout', type=float, default=3600)
    job.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if args.action == 'doctor':
            doctor()
            return 0
        if args.action == 'simulate':
            from src.pipeline.driver import simulate as run_simulation
            state = run_simulation(ROOT, local_path(args.spec), local_path(args.run) if args.run else None, args.until, args.dry_run)
            if state is None:
                return 0
            return 0 if all(s.get('status') != 'failed' for s in state['stages'].values()) else 1
        if args.action == 'status':
            from src.pipeline import state as state_module
            from src import workflow
            run = local_path(args.run_directory)
            if (run / 'state.json').is_file():
                state = state_module.load(run)
                print(json.dumps(state, indent=2) if args.json else state_module.summary_text(state))
                return 0
            result = workflow.status(ROOT, args.run_directory)
            print(json.dumps(result, indent=2))
            return 0 if all(x['matches_snapshot'] for x in result['snapshot_integrity']) else 1
        if args.action == 'test':
            return run_tests(args)
        if args.action == 'results-export':
            from src.results.saved_case import export_saved_case
            print(export_saved_case(local_path(args.run_directory), args.case, args.time, local_path(args.output)))
            return 0
        if args.action == 'results-serve':
            from src.results.server import serve
            serve(local_path(args.export_directory), args.port, local_path(args.run) if args.run else None)
            return 0
        if args.action.startswith('review-'):
            from src import workflow
            from src.requirements import review
            if args.action == 'review-import':
                from src.cad.step_preview import preview_step
                source = local_path(args.step)
                _, _, specification = workflow.read_spec(ROOT, args.project)
                label = re.sub('[^a-zA-Z0-9_-]', '-', args.label)[:48] or 'requirements'
                folder = ROOT / 'runs' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + label + '-' + uuid.uuid4().hex[:8])
                folder.mkdir()
                model = preview_step(source, folder / 'model.json')
                state = review.initialize_review(folder, source, model, specification)
                result = {'review_directory': str(folder.relative_to(ROOT)), 'approved': state['approved'],
                          'issues': state['issues'], 'faces': len(model['faces']), 'candidate_ports': len(model['virtual_faces']),
                          'serve_command': '.venv/bin/python tools/workbench.py review-serve ' + str(folder.relative_to(ROOT))}
            else:
                folder = local_path(args.review_directory)
                if args.action == 'review-serve':
                    from src.requirements.server import serve
                    serve(folder, args.port)
                    return 0
                if args.action == 'review-handoff':
                    result = review.handoff(folder)
                    result = {'handoff_directory': result['handoff_directory'], 'status': result['manifest']['status']}
                elif args.action == 'review-verify':
                    result = review.verify_handoff(folder)
                else:
                    if args.action == 'review-draft':
                        data = json.loads(local_path(args.draft).read_text())
                        state = review.save_draft(folder, data, args.revision)
                    else:
                        state = review.read_state(folder)
                    result = {key: state[key] for key in ('draft', 'draft_sha256', 'approval', 'approved', 'issues')}
            print(json.dumps(result, indent=2))
            return 0
        if args.action in ('check', 'prepare'):
            from src import workflow
            if args.action == 'check':
                _, _, spec = workflow.read_spec(ROOT, args.project)
                result = workflow.check_spec(ROOT, spec)
                code = 0 if result['intake_complete'] else 1
            else:
                result = workflow.prepare(ROOT, args.project, args.label)
                code = 0
            print(json.dumps(result, indent=2))
            return code
        return run_job(args)
    except (OSError, RuntimeError, ValueError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
