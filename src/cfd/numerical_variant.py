"""Clone a reviewed CHT checkpoint with energy equation relaxation changed.

Execute through workbench job. Geometry, physical fields and BCs are copied
byte-for-byte; the new iteration clock starts at zero. No inherited acceptance.
"""
import argparse
import json
import math
from pathlib import Path
import re
import shutil
import tempfile

from src.foam.hashing import digest


def clone(source, target, iteration, solid_relaxation, fluid_relaxation=None):
    source, target = Path(source).resolve(), Path(target).resolve()
    if target.exists():
        raise ValueError('Target must not exist')
    changes = {'solid': solid_relaxation}
    if fluid_relaxation is not None:
        changes['fluid'] = fluid_relaxation
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 1 for v in changes.values()):
        raise ValueError('Energy relaxation must be finite in (0,1]')
    iteration = str(iteration)
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', iteration) or float(iteration) <= 0:
        raise ValueError('Explicit positive source iteration required')
    checkpoint = source / iteration
    review = json.loads((source / 'bounded-review.json').read_text())
    evidence = review['chunks'][-1]
    if (evidence['iteration'] != float(iteration) or not evidence['phase_margin_screen_pass']
            or evidence['transport_validity'].get('within_declared_range') is False):
        raise ValueError('Selected checkpoint must have a current passing phase/range screen')
    if review['status'] not in ('iteration_limit_not_converged', 'numerical_screen_pass_requires_independent_model_mesh_review'):
        raise ValueError('Source must be stopped with a completed checkpoint')
    settings = json.loads((source / 'settings.json').read_text())
    model = settings.get('turbulence_model', 'kEpsilon')
    turbulence = {'laminar': [], 'kEpsilon': ['k', 'epsilon', 'nut', 'alphat'],
                  'kOmegaSST_spalding': ['k', 'omega', 'nut', 'alphat']}[model]
    required = {'fluid': ['T', 'U', 'p', 'p_rgh', 'phi', 'rho'] + turbulence, 'solid': ['T']}
    for region, fields in required.items():
        for name in fields:
            if not (checkpoint / region / name).is_file():
                raise ValueError(f'Missing restart field {region}/{name} for a {model} case')
    changed_solutions, change_record = {}, {}
    for region, relaxation in changes.items():
        key = region + '_enthalpy_relaxation'
        solution = (source / f'system/{region}/fvSolution').read_text()
        # Restrict replacement to equations inside relaxationFactors; do not
        # touch the h linear solver or any momentum/turbulence coefficients.
        pattern = r'(relaxationFactors\s*\{[^{}]*(?:fields\s*\{[^{}]*\}\s*)?equations\s*\{[^{}]*?\bh\s+)[^;]+;'
        changed, count = re.subn(pattern, lambda m: m[1] + str(relaxation) + ';', solution)
        if count != 1:
            raise ValueError(f'Cannot identify unique {region} enthalpy equation relaxation')
        changed_solutions[region] = changed
        change_record[key] = {'before': settings[key], 'after': relaxation}
    source_files = [p for folder in ['constant', 'system', iteration] for p in (source / folder).rglob('*') if p.is_file()]
    hashes = {str(p.relative_to(source)): digest(p) for p in source_files}
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=target.name + '.building-', dir=target.parent))
    try:
        for folder in ['constant', 'system']:
            shutil.copytree(source / folder, temporary / folder)
        shutil.copytree(checkpoint, temporary / '0')
        for relative, expected in hashes.items():
            copied = temporary / ('0/' + relative[len(iteration)+1:] if relative.startswith(iteration + '/') else relative)
            if digest(copied) != expected or digest(source / relative) != expected:
                raise ValueError('Source changed or copy hash mismatch')
        archive = temporary / 'source-checkpoint'
        archive.mkdir()
        for name in ['settings.json', 'bounded-review.json', 'manifest.json', 'summary.json']:
            if (source / name).is_file():
                shutil.copy2(source / name, archive / name)
        for region, changed in changed_solutions.items():
            (temporary / f'system/{region}/fvSolution').write_text(changed)
            settings[region + '_enthalpy_relaxation'] = changes[region]
        (temporary / 'settings.json').write_text(json.dumps(settings, indent=2) + '\n')
        provenance = {'source_case': str(source), 'source_iteration': iteration, 'new_initial_iteration': 0,
                      'source_files_sha256': hashes, 'source_review_sha256': digest(source / 'bounded-review.json'),
                      'changes': change_record,
                      'physical_fields_and_boundary_conditions_changed': False,
                      'source_sha256': digest(Path(__file__))}
        (temporary / 'numerical-variant.json').write_text(json.dumps(provenance, indent=2) + '\n')
        shutil.copy2(__file__, temporary / 'numerical_variant.py')
        manifest = json.loads((source / 'manifest.json').read_text())
        for key in ['solver_command', 'solver_exit_code', 'solver_logs', 'runner_sha256', 'fixed_input_sha256']:
            manifest.pop(key, None)
        manifest.update(configuration=settings, simulation_executed=False, numerically_verified=False,
                        execution_status='not_started', numerical_variant=provenance)
        (temporary / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        temporary.rename(target)
    except BaseException:
        shutil.rmtree(temporary)
        raise
    return provenance


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('--iteration', required=True)
    parser.add_argument('--solid-relaxation', type=float, required=True)
    parser.add_argument('--fluid-relaxation', type=float)
    args = parser.parse_args()
    clone(args.source, args.target, args.iteration, args.solid_relaxation, args.fluid_relaxation)
