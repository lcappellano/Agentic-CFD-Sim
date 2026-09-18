"""Export a stopped case's saved fields for the read-only 3D viewer."""
import argparse
import json
from pathlib import Path
import re

from src.foam.hashing import digest
from src.pipeline.status import case_status
from src.results.export import collect_fields, finite, load_json, now


def verify_saved_inputs(run, case_name, time):
    run = Path(run).resolve()
    case = (run / case_name).resolve()
    if not case.is_relative_to(run) or case == run or not re.fullmatch(r'\d+(?:\.\d+)?', time) or float(time) <= 0:
        raise ValueError('Invalid saved case/time')
    manifest = load_json(case / 'manifest.json')
    review = load_json(case / 'bounded-review.json')
    summary = load_json(case / 'summary.json')
    if manifest.get('execution_status') not in ('succeeded', 'failed') or review.get('status') == 'running':
        raise ValueError('Export only a stopped case')
    if not manifest.get('simulation_executed') or summary['latest_fields'] != time:
        raise ValueError('Saved summary does not identify the requested executed fields')
    times = [p.name for p in case.iterdir() if p.is_dir() and re.fullmatch(r'\d+(?:\.\d+)?', p.name)]
    if not times or max(times, key=float) != time:
        raise ValueError('Newer fields need a matching review')
    last = review['chunks'][-1]
    if last['iteration'] != float(time):
        raise ValueError('Review does not match the saved fields')
    decision = case_status(manifest, review, last)
    hashes = {p.relative_to(run).as_posix(): digest(p) for p in
              (case / 'manifest.json', case / 'bounded-review.json', case / 'summary.json', case / 'settings.json')}
    return decision, summary, hashes


def export_saved_case(run, case_name, time, output):
    run, output = Path(run).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('Use a fresh versioned export directory')
    decision, summary, hashes = verify_saved_inputs(run, case_name, time)
    case = run / case_name
    surfaces, slices, points, extrema = collect_fields(run, case, time, hashes)
    # The copper side of the interface coincides with the fluid wall; draw it once.
    surfaces = [s for s in surfaces if not (s['region'] == 'solid' and s.get('patch') == 'solid_to_fluid')]
    settings = load_json(case / 'settings.json')
    result = dict(
        schema_version=1, exported_at=now(), run_id=run.name, case_name=case_name, time=time,
        coordinate_units='mm', field_association='triangle',
        fields={'T': {'units': 'K'}, 'p': {'units': 'Pa', 'reference': 'absolute'}, 'U': {'units': 'm/s', 'components': 3}, 'speed': {'units': 'm/s'}},
        bounds_mm=[[min(p[a] for p in points) * 1000 for a in range(3)], [max(p[a] for p in points) * 1000 for a in range(3)]],
        surfaces=surfaces, slices=slices, summary=summary, acceptance=decision,
        temperature_extrema_K=extrema, temperature_limit_K=settings['temperature_limit_K'], pressure_reference_Pa=101325,
        operating_point={'flow_L_min': settings.get('volume_flow_L_min'), 'outlet_absolute_pressure_Pa': settings['outlet_absolute_pressure_Pa'],
                         'differential_target_Pa': settings.get('target_pump_pressure_rise_Pa')},
        provenance={'input_sha256': hashes, 'solver': settings['solver'], 'exporter_sha256': digest(Path(__file__)),
                    'pressure_definition': 'Absolute static pressure in Pa.'})
    for relative, expected in hashes.items():
        if digest(run / relative) != expected:
            raise ValueError('Input changed during export: ' + relative)
    finite(result)
    output.mkdir(parents=True)
    payload = output / 'results.json'
    payload.write_text(json.dumps(result, separators=(',', ':'), allow_nan=False) + '\n')
    metadata = output / 'summary.json'
    metadata.write_text(json.dumps({key: result[key] for key in ('case_name', 'time', 'acceptance', 'temperature_extrema_K', 'summary', 'operating_point')}, indent=2) + '\n')
    manifest = dict(schema_version=1, export_kind='saved_case_v1', summary_sha256=digest(metadata), run_id=run.name,
                    case_name=case_name, time=time, files={'results.json': digest(payload)}, input_sha256=hashes, frozen=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--case', required=True, help='case directory relative to the run')
    parser.add_argument('--time', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(export_saved_case(args.run, args.case, args.time, args.output))


if __name__ == '__main__':
    main()
