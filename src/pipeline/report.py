"""Generate report.md from state.json; agents do not hand-write reports."""
import json
from pathlib import Path

from src.pipeline.status import DESCRIPTIONS

NEXT_STEPS = {
    'iteration_limit_not_converged': ('Raise schedule.maximum and rerun (continues from the last chunk). If the energy pickup is still '
                                      'crawling, set initialization.temperature_from_prescreen: true for a fresh case, or clone the '
                                      'checkpoint with numerical_variant and enthalpy relaxation 1.0.'),
    'numerical_screen_pass_requires_independent_model_mesh_review': 'Run a paired finer mesh (mesh.profile tet-fine) and compare; review y+ and property ranges in the audit.',
    'numerical_screen_pass_but_phase_invalid': 'Wall temperatures reach saturation: raise outlet pressure or flow, or the single-phase model does not apply.',
    'persistent_single_phase_model_violation_not_design_failure': 'Liquid screen fails in consecutive chunks: change operating point; do not continue this case.',
    'outside_transport_fit_range': 'Widen materials.fit_range_K (or use constant transport) and rebuild the case.',
    'nonfinite_solver_residual': 'Startup diverged: try numerics.profile tet-robust-slow-energy, then numerical_variant to 0.9.',
    'nonfinite_saved_state': 'Startup diverged: try numerics.profile tet-robust-slow-energy and a finer mesh near the inlet.',
    'solver_or_postprocessing_failed': 'Read logs/solve.log and the case log.solver* files; fix the cause in src/, not the case.',
}


SETTLED_GATES = {'residuals', 'pressure_drift'}


def next_step(state):
    """Advice for the case's stop reason. An iteration limit with settled temperatures and balances
    is a residual floor, so the advice is a restart or a finer mesh, never more iterations."""
    case = state.get('case') or {}
    reason = case.get('stop_reason')
    if reason != 'iteration_limit_not_converged':
        return NEXT_STEPS.get(reason)
    failed = {k for k, v in (case.get('numerical_checks') or {}).items() if not v}
    if not failed or not failed <= SETTLED_GATES:
        return NEXT_STEPS[reason]
    residuals = [c for c in (case.get('audit_failed') or []) if c.startswith('residual:')]
    fluid = [c for c in residuals if c.startswith('residual:fluid:')]
    solid = [c for c in residuals if c.startswith('residual:solid:')]
    gradient = (((state.get('spec') or {}).get('numerics') or {}).get('solid_gradient') or '')
    case_path = f"runs/{state.get('run')}/{case['path']}" if case.get('path') and state.get('run') else '<this case>'
    parts = ['Temperatures and balances have settled and only the residual/pressure-drift gates fail: this is a residual '
             'floor, so raising schedule.maximum will not help.']
    if solid and gradient.startswith('cellLimited'):
        parts.append(f'The solid h floor comes from the limited solid gradient: restart with numerics.profile tet-robust-restart '
                     f'and initialization.fields_from_case: {case_path} (same mesh; continues the settled flow).')
    if fluid or 'pressure_drift' in failed:
        parts.append('The fluid residuals / pressure-drop wander are a mesh-and-scheme floor: run a paired finer mesh (a smaller '
                     'refinement box over the channels, or mesh.profile tet-fine) and compare against the mesh gates; if the '
                     'floor persists, prism layers or a monitor-based gate are the code-level options.')
    elif solid and not gradient.startswith('cellLimited'):
        parts.append('The solid h floor persists with the unlimited gradient; review the solid mesh near the interface.')
    return ' '.join(parts)


def write_report(run, state, resolved=None):
    run = Path(run)
    lines = [f'# {state["run"]}', '']
    if resolved:
        op = resolved['operating']
        lines += ['## Operating point', '', '| quantity | value |', '| --- | --- |']
        filled = (state.get('autofill') or {}).get('filled') or {}
        for key, value in op.items():
            lines.append(f'| {key} | {value}{" (estimated by the prescreen)" if key in filled else ""} |')
        lines += ['', f"Materials: {resolved['materials']['solid']} / {resolved['materials']['fluid']} "
                  f"({resolved['materials']['transport']} transport). Mesh profile {resolved['mesh']['name']}, "
                  f"numerics {resolved['numerics']['name']}, acceptance {resolved['acceptance']['name']}.", '']
    if state.get('autofill'):
        auto = state['autofill']
        lines += ['## Estimated operating point', '',
                  'The review and the spec left the values marked above open, so the prescreen chose them (correlation estimate, not CFD):', '']
        lines += ['- ' + reason for reason in auto['reasons']] + ['- WARNING: ' + warning for warning in auto['warnings']]
        lines += ['', 'To choose them yourself, set `operating.volume_flow_L_min` and `operating.outlet_absolute_pressure_bar` in the spec '
                  '(or `decision.required: true` to stop after the prescreen) and rerun with `--run`.', '']
    prescreen = state['stages'].get('prescreen', {})
    if prescreen.get('table'):
        lines += ['## Prescreen', '', prescreen['table']]
        if resolved and resolved.get('decision'):
            decision = resolved['decision']
            lines += [f"Operator decision: {decision.get('operator', '?')} — {decision.get('note', '')}", '']
    if state.get('status') == 'awaiting_operator_decision':
        lines += ['## Decision needed', '', state.get('decision_prompt', ''), '',
                  'Add the chosen values to the spec (optionally a `decision` block with `operator` and `note`) and rerun '
                  f'`tools/workbench.py simulate <spec> --run {run}`. Geometry and materials are reused.', '']
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
        advice = next_step(state)
        if advice:
            lines += ['', 'Next step: ' + advice]
        if case.get('viewer'):
            lines += ['', f"Viewer: `python tools/workbench.py results-serve {case['viewer']} --run {run}`"]
    if state.get('warnings'):
        lines += ['', '## Warnings', ''] + ['- ' + w for w in state['warnings']]
    text = '\n'.join(lines) + '\n'
    (run / 'report.md').write_text(text)
    return text
