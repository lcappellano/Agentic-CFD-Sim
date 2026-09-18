"""Chunked solver execution with numerical, transport-range and phase gates.

Each chunk ends with a summary and an assessment saved to ``bounded-review.json``.
The driver stops on nonfinite state, transport extrapolation, a persistent
single-phase violation, or a passing numerical screen. Passing the screen is
evidence for independent review, not acceptance.
"""
import argparse
import contextlib
import json
import math
from pathlib import Path

from src.cfd.run_case import run, FIXED_FILES
from src.cfd.summarize_case import summarize
from src.foam.fields import PolyMesh
from src.foam.hashing import digest
from src.foam.logs import residual_maxima
from src.foam.monitors import monitor_rows, full_window
from src.thermal.saturation import saturation_pressure, TRIPLE_K, CRITICAL_K

STOP_STATUSES = {
    'iteration_limit_not_converged': 'Ran to the authorised iteration limit without passing the numerical screen.',
    'numerical_screen_pass_requires_independent_model_mesh_review': 'All numerical gates pass on this mesh; model and mesh review remain.',
    'numerical_screen_pass_but_phase_invalid': 'Converged numerically but the single-phase liquid screen fails.',
    'persistent_single_phase_model_violation_not_design_failure': 'Two consecutive chunks violate the liquid screen; the model, not the design, is out of range.',
    'outside_transport_fit_range': 'Fluid temperatures left the declared transport fit interval.',
    'nonfinite_solver_residual': 'Solver produced nonfinite residuals.',
    'nonfinite_saved_state': 'Saved fields contain nonfinite values.',
    'solver_or_postprocessing_failed': 'The solver or a postprocessing step raised an error.',
}


def phase_counts(temperatures, pressures, margin):
    if len(pressures) == 1:
        pressures = pressures * len(temperatures)
    if len(temperatures) == 1:
        temperatures = temperatures * len(pressures)
    if len(temperatures) != len(pressures):
        raise ValueError('Phase field count mismatch')
    result = {'nonfinite': 0, 'invalid_pressure': 0, 'outside_saturation_correlation': 0,
              'above_saturation': 0, 'below_required_margin': 0}
    for t, p in zip(temperatures, pressures):
        if not math.isfinite(t) or not math.isfinite(p):
            result['nonfinite'] += 1
            continue
        if p <= 0:
            result['invalid_pressure'] += 1
            continue
        if not TRIPLE_K <= t <= CRITICAL_K or t + margin > CRITICAL_K:
            result['outside_saturation_correlation'] += 1
            continue
        if p < saturation_pressure(t):
            result['above_saturation'] += 1
        if p < saturation_pressure(t + margin):
            result['below_required_margin'] += 1
    return result


def assess(case, summary, criteria):
    case = Path(case)
    settings = json.loads((case / 'settings.json').read_text())
    latest = case / summary['latest_fields']
    window = criteria['final_window_iterations']
    fluid = PolyMesh(case / 'constant/fluid/polyMesh')
    bulk_t = fluid.read_internal(latest / 'fluid/T')
    bulk_p = fluid.read_internal(latest / 'fluid/p')
    wall_t = fluid.read_boundary(latest / 'fluid/T', 'fluid_to_solid')
    wall_p = fluid.read_boundary(latest / 'fluid/p', 'fluid_to_solid')
    margin = criteria['local_liquid_saturation_margin_K']
    phase = {'bulk': phase_counts(bulk_t, bulk_p, margin), 'wetted': phase_counts(wall_t, wall_p, margin)}
    maxima = residual_maxima(case, float(latest.name), window)
    dissipation = 'omega' if settings.get('turbulence_model') == 'kOmegaSST_spalding' else 'epsilon'
    expected = {f'fluid:{name}' for name in ('Ux', 'Uy', 'Uz', 'h', 'p_rgh', 'k', dissipation)} | {'solid:h'}
    last, ranges = summary['monitor_last'], summary['final_window_ranges']
    expected_heat = settings['heat_flux_W_m2'] * settings['heated_area_m2']
    energy = summary.get('energy_imbalance_with_port_diffusion_fraction')
    window_ok = all(full_window(monitor_rows(case, name), float(latest.name), window)
                    for name in ('heatedMax', 'wettedMax', 'inletPressure', 'outletPressure'))
    checks = {
        'complete_monitor_window': window_ok,
        'heat_input': abs(last['heatedPower'] - expected_heat) / expected_heat <= criteria['heat_input_relative'],
        'mass': summary['mass_imbalance_fraction'] <= criteria['mass_balance_relative'],
        'energy': energy is not None and energy <= criteria['energy_balance_relative'],
        'interface_power': abs(last['interfacePower'] + last['fluidPower']) / abs(last['heatedPower']) <= criteria['interface_power_relative'],
        'temperature_drift': max(ranges['heatedMax'], ranges['wettedMax']) <= criteria['temperature_range_K'],
        'pressure_drift': ranges['inletPressure'] / max(abs(summary['pressure_drop_Pa']), 1e-30) <= criteria['pressure_drop_range_relative'],
        'residuals': expected.issubset(maxima) and all(
            v['finite'] and v['window_complete'] and v['initial'] <= criteria['initial_residual_max']
            and v['linear_final'] <= criteria['linear_final_residual_max'] for v in maxima.values()),
    }
    return {'iteration': float(latest.name), 'numerical_checks': checks, 'numerical_screen_pass': all(checks.values()),
            'residual_maxima': maxima, 'phase': phase, 'transport_validity': summary['transport_validity'],
            'phase_margin_screen_pass': all(not any(v.values()) for v in phase.values()),
            'heated_maximum_K': summary['heated_maximum_location']['temperature_K'],
            'pressure_drop_Pa': summary['pressure_drop_Pa'], 'total_pressure_drop_Pa': summary['total_pressure_drop_Pa']}


def stop_reason(evidence, previous_phase_failure):
    if any(not v['finite'] for v in evidence.get('residual_maxima', {}).values()):
        return 'nonfinite_solver_residual', False
    phase = evidence['phase']
    if any(v['nonfinite'] for v in phase.values()):
        return 'nonfinite_saved_state', False
    if evidence['transport_validity'].get('within_declared_range') is False:
        return 'outside_transport_fit_range', False
    failed = any(v['invalid_pressure'] or v['outside_saturation_correlation'] or v['above_saturation'] for v in phase.values())
    if failed and previous_phase_failure:
        return 'persistent_single_phase_model_violation_not_design_failure', True
    if evidence['numerical_screen_pass']:
        if failed:
            return 'numerical_screen_pass_but_phase_invalid', True
        return 'numerical_screen_pass_requires_independent_model_mesh_review', False
    return None, failed


def fixed_inputs(case):
    files = [Path(case) / name for name in FIXED_FILES]
    files += [Path(__file__).with_name(name) for name in ('run_case.py', 'summarize_case.py', 'transport.py', 'run_bounded.py')]
    return {str(p.resolve()): digest(p) for p in files if p.is_file()}


def load_criteria(criteria):
    if isinstance(criteria, dict):
        return criteria
    data = json.loads(Path(criteria).read_text())
    return data.get('acceptance_criteria', data)


def execute(case, criteria, ranks=4, initial=100, chunk=500, maximum=6000, continue_run=False):
    case = Path(case).resolve()
    criteria = load_criteria(criteria)
    if not 0 < initial <= maximum or chunk <= 0:
        raise ValueError('Invalid bounded iteration schedule')
    record = {'schema_version': 2, 'fixed_inputs_sha256': fixed_inputs(case), 'criteria': criteria,
              'schedule': {'initial': initial, 'chunk': chunk, 'maximum': maximum}, 'chunks': [],
              'status': 'running', 'accepted': False}
    record_path = case / 'bounded-review.json'
    previous_failure, target = False, initial
    if record_path.exists():
        if not continue_run:
            raise ValueError('Existing bounded record: pass continue_run=True to extend it')
        previous = json.loads(record_path.read_text())
        if previous['status'] not in ('iteration_limit_not_converged', 'running'):
            raise ValueError(f'Cannot continue a run stopped for {previous["status"]}')
        if previous['fixed_inputs_sha256'] != record['fixed_inputs_sha256']:
            raise ValueError('Mesh, settings, materials or driver source changed since the last chunk')
        if maximum <= previous['chunks'][-1]['iteration']:
            raise ValueError('New maximum must extend the saved run')
        record = previous
        record.setdefault('extensions', []).append({'maximum': maximum, 'chunk': chunk})
        previous_failure = any(v['invalid_pressure'] or v['above_saturation'] for v in record['chunks'][-1]['phase'].values())
        target = min(maximum, int(record['chunks'][-1]['iteration']) + chunk)
    elif continue_run:
        raise ValueError('No bounded record to continue')
    record_path.write_text(json.dumps(record, indent=2, allow_nan=False) + '\n')
    while True:
        try:
            run(case, ranks=ranks, resume=bool(record['chunks']), end_iteration=target)
            with (case / f'summary-{target}.log').open('w') as log, contextlib.redirect_stdout(log):
                summary = summarize(case, criteria['final_window_iterations'])
            (case / f'summary-{target}.json').write_text(json.dumps(summary, indent=2) + '\n')
            evidence = assess(case, summary, criteria)
        except Exception as error:
            record.update(status='solver_or_postprocessing_failed',
                          error={'type': type(error).__name__, 'message': str(error), 'target_iteration': target})
            record_path.write_text(json.dumps(record, indent=2, allow_nan=False) + '\n')
            raise
        reason, previous_failure = stop_reason(evidence, previous_failure)
        evidence['stop_reason'] = reason
        record['chunks'].append(evidence)
        record['status'] = reason or ('iteration_limit_not_converged' if target >= maximum else 'running')
        record_path.write_text(json.dumps(record, indent=2, allow_nan=False) + '\n')
        print(json.dumps({'iteration': target, 'status': record['status'], 'numerical_checks': evidence['numerical_checks'],
                          'heated_maximum_K': evidence['heated_maximum_K']}), flush=True)
        if reason or target >= maximum:
            return record
        target = min(maximum, target + chunk)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    parser.add_argument('--criteria', type=Path, required=True, help='acceptance criteria JSON')
    parser.add_argument('--ranks', type=int, default=4)
    parser.add_argument('--initial', type=int, default=100)
    parser.add_argument('--chunk', type=int, default=500)
    parser.add_argument('--maximum', type=int, default=6000)
    parser.add_argument('--continue-run', action='store_true')
    args = parser.parse_args()
    execute(args.case, args.criteria, args.ranks, args.initial, args.chunk, args.maximum, args.continue_run)


if __name__ == '__main__':
    main()
