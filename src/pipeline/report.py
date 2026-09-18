"""Generate report.md from state.json; agents do not hand-write reports."""
import json
from pathlib import Path

from src.pipeline.status import DESCRIPTIONS

NEXT_STEPS = {
    'iteration_limit_not_converged': 'Raise schedule.maximum in the spec and rerun; the solve continues from the last chunk.',
    'numerical_screen_pass_requires_independent_model_mesh_review': 'Run a paired finer mesh (mesh.profile tet-fine) and compare; review y+ and property ranges in the audit.',
    'numerical_screen_pass_but_phase_invalid': 'Wall temperatures reach saturation: raise outlet pressure or flow, or the single-phase model does not apply.',
    'persistent_single_phase_model_violation_not_design_failure': 'Liquid screen fails in consecutive chunks: change operating point; do not continue this case.',
    'outside_transport_fit_range': 'Widen materials.fit_range_K (or use constant transport) and rebuild the case.',
    'nonfinite_solver_residual': 'Startup diverged: try numerics.profile tet-robust-slow-energy, then numerical_variant to 0.9.',
    'nonfinite_saved_state': 'Startup diverged: try numerics.profile tet-robust-slow-energy and a finer mesh near the inlet.',
    'solver_or_postprocessing_failed': 'Read logs/solve.log and the case log.solver* files; fix the cause in src/, not the case.',
}


def write_report(run, state, resolved=None):
    run = Path(run)
    lines = [f'# {state["run"]}', '']
    if resolved:
        op = resolved['operating']
        lines += ['## Operating point', '', '| quantity | value |', '| --- | --- |']
        for key, value in op.items():
            lines.append(f'| {key} | {value} |')
        lines += ['', f"Materials: {resolved['materials']['solid']} / {resolved['materials']['fluid']} "
                  f"({resolved['materials']['transport']} transport). Mesh profile {resolved['mesh']['name']}, "
                  f"numerics {resolved['numerics']['name']}, acceptance {resolved['acceptance']['name']}.", '']
    lines += ['## Stages', '', '| stage | status | output | summary |', '| --- | --- | --- | --- |']
    for name, stage in state['stages'].items():
        summary = ', '.join(f'{k}={v}' for k, v in (stage.get('summary') or {}).items())
        lines.append(f"| {name} | {stage.get('status')} | {stage.get('output') or ''} | {summary} |")
    case = state.get('case')
    if case:
        lines += ['', '## Result', '', f"Status: **{case['status']}** — {DESCRIPTIONS[case['status']]}", '',
                  f"Stop reason: `{case.get('stop_reason')}` at iteration {case.get('iteration')}.", '']
        if case.get('heated_maximum_C') is not None:
            lines += ['| quantity | value |', '| --- | --- |',
                      f"| heated maximum | {case['heated_maximum_C']:.2f} °C ({case['heated_maximum_K']:.2f} K) |",
                      f"| temperature limit | {case['temperature_limit_C']:.2f} °C |",
                      f"| wetted maximum | {case['wetted_maximum_C']:.2f} °C |",
                      f"| static pressure drop | {case['pressure_drop_bar']:.4f} bar |",
                      f"| total pressure drop | {case['total_pressure_drop_bar']:.4f} bar |",
                      f"| mass imbalance | {case.get('mass_imbalance_fraction')} |",
                      f"| energy imbalance | {case.get('energy_imbalance_fraction')} |", '']
        failed = [k for k, v in (case.get('numerical_checks') or {}).items() if not v]
        if failed:
            lines.append('Failed numerical checks: ' + ', '.join(failed) + '.')
        if case.get('audit_failed'):
            lines.append('Failed audit checks: ' + ', '.join(case['audit_failed']) + '.')
        if case.get('stop_reason') in NEXT_STEPS:
            lines += ['', 'Next step: ' + NEXT_STEPS[case['stop_reason']]]
        if case.get('viewer'):
            lines += ['', f"Viewer: `python tools/workbench.py results-serve {case['viewer']} --run {run}`"]
    if state.get('warnings'):
        lines += ['', '## Warnings', ''] + ['- ' + w for w in state['warnings']]
    text = '\n'.join(lines) + '\n'
    (run / 'report.md').write_text(text)
    return text
