"""Initialise a fresh case from a solved case on a different mesh of the same geometry.

OpenFOAM ``mapFields -consistent`` maps every volume field the two cases share, region by
region, from the source's latest time into the target's ``0``. The target keeps its own
boundary conditions, ``phi`` is rebuilt by the solver, and postprocessing fields the target
does not declare are removed again. A refined mesh started this way skips the potential-flow
start, whose singular corner velocities a fine mesh resolves as spikes (166 m/s and -2000 bar
at iteration 20 on the 7.6 M cell manifold), and most of the thermal pseudo-transient.
"""
import argparse
import json
from pathlib import Path

from src.cfd.warm_start import INTERNAL, NONUNIFORM, NONFINITE, MATCHING, _cell_count
from src.foam.environment import run_tool
from src.foam.fields import latest_time, parse_values, solved_times
from src.foam.hashing import digest

METHODS = ('mapNearest', 'cellVolumeWeight', 'correctedCellVolumeWeight', 'direct')
REGIONS = ('fluid', 'solid')


def check_compatible(source, target):
    """Same operating point and same extracted geometry; target fresh. Returns the source time directory."""
    source, target = Path(source).resolve(), Path(target).resolve()
    if solved_times(target):
        raise ValueError('Target already contains solved times')
    if any(target.glob('processor[0-9]*')):
        raise ValueError('Map before decomposition')
    source_settings = json.loads((source / 'settings.json').read_text())
    target_settings = json.loads((target / 'settings.json').read_text())
    for key in MATCHING['fields']:
        if source_settings.get(key) != target_settings.get(key):
            raise ValueError('Boundary conditions differ: ' + key)
    for name in ('source_sha256', 'requirements_sha256'):
        manifests = [json.loads((case / 'geometry-manifest.json').read_text()).get(name) for case in (source, target)]
        if manifests[0] is None or manifests[0] != manifests[1]:
            raise ValueError('Cases come from different geometry (' + name + ')')
    latest = latest_time(source)
    if latest is None or float(latest.name) <= 0:
        raise ValueError('No solved fields available')
    return latest


def _verify(target, region, name, cells, fit):
    text = (target / '0' / region / name).read_text()
    match = INTERNAL.search(text)
    if not match:
        raise ValueError(f'Unsupported mapped {region}/{name} encoding')
    payload = match.group(1)
    declared = NONUNIFORM.match(payload)
    if declared is not None:
        if int(declared.group(1)) != cells:
            raise ValueError(f'{region}/{name}: mapped field size differs from mesh cells')
        if NONFINITE.search(payload):
            raise ValueError(f'{region}/{name}: nonfinite mapped values')
    if name == 'T':
        values = parse_values(payload)
        if not values or min(values) <= 0:
            raise ValueError('Invalid mapped temperature')
        if fit is not None and (min(values) < fit['Tmin_K'] or max(values) > fit['Tmax_K']):
            raise ValueError('Mapped fluid temperature outside target transport fit range')
    return declared is not None


def map_from_case(source, target, method='mapNearest'):
    """Map the shared volume fields of ``source`` (latest time) onto ``target/0`` with mapFields."""
    if method not in METHODS:
        raise ValueError(f'method must be one of {METHODS}')
    source, target = Path(source).resolve(), Path(target).resolve()
    latest = check_compatible(source, target)
    target_settings = json.loads((target / 'settings.json').read_text())
    folder = target / 'initialization'
    if folder.exists():
        raise ValueError('Initialize a fresh case only')
    folder.mkdir()
    declared = {region: {p.name for p in (target / '0' / region).iterdir() if p.is_file()} for region in REGIONS}
    before = {region: {name: (target / '0' / region / name).read_bytes() for name in declared[region]} for region in REGIONS}
    records = {}
    for region in REGIONS:
        command = ['mapFields', str(source), '-case', str(target), '-sourceTime', latest.name, '-sourceRegion', region,
                   '-targetRegion', region, '-consistent', '-mapMethod', method]
        run_tool(command, target, folder / f'log.mapFields.{region}')
        for path in (target / '0' / region).iterdir():
            if path.is_file() and path.name not in declared[region]:
                path.unlink()  # postprocessing output of the source (gradT, yPlus, ...) that the target never declared
        cells = _cell_count(target, region)
        fit = target_settings.get('transport_polynomials') if region == 'fluid' else None
        records[region] = {}
        for name in sorted(declared[region]):
            path = target / '0' / region / name
            if path.read_bytes() == before[region][name]:
                continue  # not present in the source time (e.g. a field the source model did not carry)
            nonuniform = _verify(target, region, name, cells, fit)
            records[region][name] = {'source': str(latest / region / name), 'sha256': digest(path), 'nonuniform': nonuniform}
        if not records[region]:
            raise ValueError(f'{region}: mapFields changed no field')
    record = {'source_case': str(source), 'source_iteration': latest.name, 'method': method, 'fields': records,
              'selection': 'internal and patch values mapped; target boundary condition types retained; phi rebuilt by the solver'}
    (folder / 'record.json').write_text(json.dumps(record, indent=2) + '\n')
    manifest_path = target / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['mapped_initialization'] = record
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('--method', default='mapNearest', choices=METHODS)
    args = parser.parse_args()
    print(json.dumps(map_from_case(args.source, args.target, args.method), indent=2))


if __name__ == '__main__':
    main()
