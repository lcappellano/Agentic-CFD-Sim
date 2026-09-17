#!/usr/bin/env python3
"""Local job recording for Linux/WSL. Standard library only, Python 3.10+."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
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
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


@contextmanager
def job_lock():
    import fcntl
    folder = ROOT / 'runs'
    folder.mkdir(exist_ok=True)
    with (folder / '.job.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another recorded job is running; wait for it to finish.')
        yield


def doctor():
    executables = ['git', 'codex', 'python3', 'FreeCADCmd', 'freecadcmd',
                   'gmsh', 'blockMesh', 'snappyHexMesh', 'checkMesh',
                   'chtMultiRegionFoam', 'chtMultiRegionSimpleFoam',
                   'foamRun', 'foamMultiRun', 'mpirun', 'paraview']
    result = {
        'platform': platform.platform(), 'python': sys.version.split()[0],
        'project_root': str(ROOT), 'logical_cpus': os.cpu_count(),
        'wsl_distribution': os.environ.get('WSL_DISTRO_NAME'),
        'OpenFOAM_version_from_environment': os.environ.get('WM_PROJECT_VERSION'),
        'OpenFOAM_directory_from_environment': os.environ.get('WM_PROJECT_DIR'),
        'executables_on_PATH': {x: shutil.which(x) for x in executables},
        'note': 'Discovery only. A path does not prove a usable installation. '
                'Source the installed OpenFOAM environment before checking it.'
    }
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


def run_job(args):
    if os.name != 'posix':
        raise RuntimeError('Run this starter job recorder inside Linux/WSL.')
    command = args.command
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        raise ValueError('Supply a command after --.')
    if args.timeout <= 0 or not math.isfinite(args.timeout):
        raise ValueError('Timeout must be a finite positive number of seconds.')
    cwd = (ROOT / args.cwd).resolve()
    cwd.relative_to(ROOT)
    if not cwd.is_dir():
        raise ValueError('Working directory does not exist.')
    inputs = []
    for value in args.input:
        path = (ROOT / value).resolve()
        path.relative_to(ROOT)
        inputs.append({'path': str(path.relative_to(ROOT)), 'sha256': digest(path)})
    label = re.sub('[^a-zA-Z0-9_-]', '-', args.label)[:48] or 'job'
    with job_lock():
        folder = ROOT / 'runs' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
                                  + '-' + label + '-' + uuid.uuid4().hex[:8])
        folder.mkdir()
        record = {'schema_version': 1, 'status': 'running', 'started_at': now(),
                  'command': command, 'cwd': str(cwd.relative_to(ROOT)),
                  'inputs': inputs, 'timeout_seconds': args.timeout,
                  'OpenFOAM_version': os.environ.get('WM_PROJECT_VERSION'),
                  'python': sys.version.split()[0], 'numerically_verified': False}
        save(folder / 'job.json', record)
        print(f'Job: {folder.relative_to(ROOT)}', flush=True)
        started = time.monotonic()
        process = None
        try:
            with (folder / 'console.log').open('w') as log:
                process = subprocess.Popen(command, cwd=cwd, stdout=log,
                    stderr=subprocess.STDOUT, start_new_session=True)
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
            record.update(finished_at=now(), elapsed_seconds=round(time.monotonic()-started, 3))
            save(folder / 'job.json', record)
        print(json.dumps(record, indent=2))
        return 0 if record['status'] == 'succeeded' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('doctor')
    check = sub.add_parser('check', help='Check request inputs; never executes a simulation.')
    check.add_argument('--project', default='project.json')
    prepare = sub.add_parser('prepare', help='Create a versioned request snapshot without execution.')
    prepare.add_argument('--project', default='project.json')
    prepare.add_argument('--label', default='request')
    status = sub.add_parser('status', help='Read a prepared workflow and check snapshot hashes.')
    status.add_argument('run_directory')
    review_import = sub.add_parser('review-import', help='Import STEP into a versioned visual requirements review.')
    review_import.add_argument('--step', required=True)
    review_import.add_argument('--project', default='project.json')
    review_import.add_argument('--label', default='requirements')
    review_serve = sub.add_parser('review-serve', help='Open a loopback-only 3D requirements review service.')
    review_serve.add_argument('review_directory')
    review_serve.add_argument('--port', type=int, default=8765)
    for action in ('review-status', 'review-handoff', 'review-verify'):
        command = sub.add_parser(action)
        command.add_argument('review_directory')
    review_draft = sub.add_parser('review-draft', help='Save proposed selections/requirements; cannot approve.')
    review_draft.add_argument('review_directory')
    review_draft.add_argument('--draft', required=True)
    review_draft.add_argument('--revision', type=int, required=True)
    job = sub.add_parser('job')
    job.add_argument('--label', default='job')
    job.add_argument('--cwd', default='.', help='Working directory relative to project root.')
    job.add_argument('--input', action='append', default=[], help='Repeat for each input file.')
    job.add_argument('--timeout', type=float, default=3600)
    job.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if args.action == 'doctor':
            doctor()
            return 0
        if args.action.startswith('review-'):
            import workflow
            from requirements import review
            if args.action == 'review-import':
                from cad.step_preview import preview_step
                source = workflow.local_path(ROOT, args.step)
                _, _, specification = workflow.read_spec(ROOT, args.project)
                label = re.sub('[^a-zA-Z0-9_-]', '-', args.label)[:48] or 'requirements'
                folder = ROOT / 'runs' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
                                         + '-' + label + '-' + uuid.uuid4().hex[:8])
                folder.mkdir()
                model = preview_step(source, folder / 'model.json')
                state = review.initialize_review(folder, source, model, specification)
                result = {'review_directory': str(folder.relative_to(ROOT)),
                          'approved': state['approved'], 'issues': state['issues'],
                          'faces': len(model['faces']), 'candidate_ports': len(model['virtual_faces']),
                          'serve_command': 'python3 tools/workbench.py review-serve ' + str(folder.relative_to(ROOT))}
            else:
                folder = workflow.local_path(ROOT, args.review_directory)
                if args.action == 'review-serve':
                    from requirements.server import serve
                    serve(folder, args.port)
                    return 0
                if args.action == 'review-handoff':
                    result = review.handoff(folder)
                    result = {'handoff_directory': result['handoff_directory'],
                              'status': result['manifest']['status'], 'simulation_ready': False}
                elif args.action == 'review-verify':
                    result = review.verify_handoff(folder)
                else:
                    if args.action == 'review-draft':
                        data = json.loads(workflow.local_path(ROOT, args.draft).read_text())
                        state = review.save_draft(folder, data, args.revision)
                    else:
                        state = review.read_state(folder)
                    result = {key: state[key] for key in ('draft', 'draft_sha256', 'approval', 'approved', 'issues')}
            print(json.dumps(result, indent=2))
            return 0
        if args.action in ('check', 'prepare', 'status'):
            import workflow
            if args.action == 'check':
                _, _, spec = workflow.read_spec(ROOT, args.project)
                result = workflow.check_spec(ROOT, spec)
                code = 0 if result['intake_complete'] else 1
            elif args.action == 'prepare':
                result = workflow.prepare(ROOT, args.project, args.label)
                code = 0
            else:
                result = workflow.status(ROOT, args.run_directory)
                code = 0 if all(x['matches_snapshot'] for x in result['snapshot_integrity']) else 1
            print(json.dumps(result, indent=2))
            return code
        return run_job(args)
    except (OSError, RuntimeError, ValueError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
