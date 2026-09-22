"""Seed a fresh case on the same mesh from a solved case: temperatures only, or every shared field.

Only ``internalField`` entries change; the target's boundary conditions stay as built and the
flux ``phi`` is never copied (the solver rebuilds it from rho and U). The source's acceptance
status is not inherited. ``seed_temperatures`` shortens the thermal pseudo-transient of a new
point or schedule; ``seed_fields`` restarts a settled flow under changed numerics (for example
the unlimited solid gradient of profile ``tet-robust-restart``) without repeating the startup,
so a residual floor caused by a scheme can be removed from a checkpoint instead of from cold.
"""
import argparse
import json
import math
from pathlib import Path
import re

from src.foam.fields import latest_time, parse_values, solved_times
from src.foam.hashing import digest

INTERNAL = re.compile(r'internalField\s+((?:uniform\s+[^;]+|nonuniform\s+List<\w+>\s+\d+\s*\(.*?\)))\s*;', re.S)
NONUNIFORM = re.compile(r'nonuniform\s+List<\w+>\s+(\d+)\s*\(')
NONFINITE = re.compile(r'\b(?:nan|inf)\b', re.I)
NEVER_SEEDED = {'phi'}
# Settings that must agree before a field of the source makes sense in the target.
MATCHING = {'temperature': ('inlet_temperature_K', 'heat_flux_W_m2'),
            'fields': ('inlet_temperature_K', 'heat_flux_W_m2', 'mass_flow_kg_s', 'outlet_absolute_pressure_Pa')}


def _cell_count(case, region):
    owner = (case / f'constant/{region}/polyMesh/owner').read_text()
    neighbour = (case / f'constant/{region}/polyMesh/neighbour').read_text()
    return 1 + max(int(v) for text in (owner, neighbour) for v in re.findall(r'\b\d+\b', text.split('(', 1)[1].rsplit(')', 1)[0]))


def _check_payload(name, payload, cells, fit):
    """Validate one internalField payload: size, finiteness and, for T, positivity and the fit range."""
    declared = NONUNIFORM.match(payload)
    if declared is None:
        values = parse_values(payload)  # uniform: cheap, rejects nonfinite
    else:
        if int(declared.group(1)) != cells:
            raise ValueError(f'{name}: field size differs from mesh cells')
        if NONFINITE.search(payload):
            raise ValueError(f'{name}: nonfinite values')
        values = parse_values(payload) if name == 'T' else None
    if name == 'T':
        flat = [v for v in values]
        if not flat or any(not math.isfinite(v) or v <= 0 for v in flat):
            raise ValueError('Invalid initial temperature')
        if fit is not None and (min(flat) < fit['Tmin_K'] or max(flat) > fit['Tmax_K']):
            raise ValueError('Warm-start fluid temperature outside target transport fit range')


def seed(source, target, fields=None, label='fields'):
    """Copy the internal values of ``fields`` (default: every field both cases share, except phi)
    from the latest time of ``source`` into ``target/0``. Validates everything before writing anything."""
    source, target = Path(source).resolve(), Path(target).resolve()
    if solved_times(target):
        raise ValueError('Target already contains solved times')
    if any(target.glob('processor[0-9]*')):
        raise ValueError('Seed before decomposition')
    source_settings = json.loads((source / 'settings.json').read_text())
    target_settings = json.loads((target / 'settings.json').read_text())
    for key in MATCHING[label]:
        if source_settings.get(key) != target_settings.get(key):
            raise ValueError('Boundary conditions differ: ' + key)
    latest = latest_time(source)
    if latest is None or float(latest.name) <= 0:
        raise ValueError('No solved fields available')
    for region in ('fluid', 'solid'):
        for name in ('points', 'faces', 'owner', 'neighbour', 'boundary'):
            if (source / f'constant/{region}/polyMesh/{name}').read_bytes() != (target / f'constant/{region}/polyMesh/{name}').read_bytes():
                raise ValueError(f'Warm-start mesh differs: {region}/{name}')
    backup_root = target / f'initial-{label}-original'
    if backup_root.exists():
        raise ValueError('Target already seeded')
    payloads = {}
    for region in ('fluid', 'solid'):
        available = {p.name for p in (latest / region).iterdir() if p.is_file()} & {p.name for p in (target / '0' / region).iterdir() if p.is_file()}
        names = sorted((available - NEVER_SEEDED) if fields is None else set(fields))
        missing = [n for n in names if n not in available]
        if missing:
            raise ValueError(f'{region}: fields not present in both cases: ' + ', '.join(missing))
        cells = _cell_count(source, region)
        fit = target_settings.get('transport_polynomials') if region == 'fluid' else None
        for name in names:
            match = INTERNAL.search((latest / region / name).read_text())
            if not match:
                raise ValueError(f'Unsupported saved {region}/{name} encoding')
            _check_payload(name, match.group(1), cells, fit)
            if not INTERNAL.search((target / '0' / region / name).read_text()):
                raise ValueError(f'Unsupported target {region}/{name} encoding')
            payloads[(region, name)] = match.group(0)
    records = {}
    for (region, name), payload in payloads.items():
        src, dst = latest / region / name, target / '0' / region / name
        backup = backup_root / region / name
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(dst.read_bytes())
        dst.write_text(INTERNAL.sub(lambda _: payload, dst.read_text(), count=1))
        records.setdefault(region, {})[name] = {'source': str(src), 'sha256': digest(src)}
    manifest_path = target / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest[f'{label}_initialization'] = {'source_case': str(source), 'source_iteration': latest.name, 'fields': records,
                                           'selection': 'internalField only; target boundary conditions retained; phi never copied'}
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    return records


def seed_temperatures(source, target):
    """Seed only T in both regions (the historical warm start)."""
    return seed(source, target, fields=('T',), label='temperature')


def seed_fields(source, target):
    """Seed every field the two cases share (U, p, p_rgh, T, turbulence fields; never phi)."""
    return seed(source, target, fields=None, label='fields')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('--all-fields', action='store_true', help='seed every shared field, not only T')
    args = parser.parse_args()
    result = seed_fields(args.source, args.target) if args.all_fields else seed_temperatures(args.source, args.target)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
