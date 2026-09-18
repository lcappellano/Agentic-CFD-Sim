"""Machine-readable run state: one JSON file agents read instead of logs."""
from datetime import datetime, timezone
import json
from pathlib import Path

STAGES = ('handoff', 'geometry', 'mesh', 'materials', 'screen', 'case', 'solve', 'audit', 'export', 'report')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def load(run):
    path = Path(run) / 'state.json'
    if path.is_file():
        return json.loads(path.read_text())
    return {'schema_version': 1, 'run': Path(run).name, 'created': now(), 'stages': {name: {'status': 'pending'} for name in STAGES},
            'case': None, 'warnings': [], 'events': []}


def save(run, state):
    state['updated'] = now()
    path = Path(run) / 'state.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def event(state, stage, status, message=''):
    state['events'].append({'time': now(), 'stage': stage, 'status': status, 'message': message})
    state['events'] = state['events'][-200:]


def summary_text(state):
    """Under 1 KB: what an agent needs before deciding anything."""
    lines = [f"run: {state['run']}   updated: {state.get('updated', '?')}"]
    for name in STAGES:
        stage = state['stages'].get(name, {})
        status = stage.get('status', 'pending')
        extra = ''
        if stage.get('cached'):
            extra = ' (cached)'
        if stage.get('output'):
            extra += f"  -> {stage['output']}"
        if stage.get('summary'):
            extra += '  ' + ', '.join(f'{k}={v}' for k, v in stage['summary'].items())
        if stage.get('error'):
            extra += f"  ERROR: {stage['error'][:200]}"
        lines.append(f'  {name:<10} {status:<8}{extra}')
    case = state.get('case')
    if case:
        lines.append(f"result: {case['status']}  stop={case.get('stop_reason')}  iteration={case.get('iteration')}")
        if case.get('heated_maximum_C') is not None:
            lines.append(f"  heated max {case['heated_maximum_C']:.2f} C   pressure drop {case['pressure_drop_bar']:.4f} bar   "
                         f"energy imbalance {case.get('energy_imbalance_fraction')}")
        failed = [k for k, v in (case.get('numerical_checks') or {}).items() if not v]
        if failed:
            lines.append('  failed checks: ' + ', '.join(failed))
    for warning in state.get('warnings', [])[-5:]:
        lines.append('warning: ' + warning)
    return '\n'.join(lines)
