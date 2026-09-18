"""Seed internal temperatures of a fresh case from a solved case on the same mesh.

Only ``internalField`` of T changes; boundary conditions and flow fields of the
target stay as built. The source's acceptance status is not inherited.
"""
import argparse
import json
import math
from pathlib import Path
import re

from src.foam.fields import latest_time, parse_values, solved_times
from src.foam.hashing import digest

INTERNAL = re.compile(r'internalField\s+((?:uniform\s+[^;]+|nonuniform\s+List<scalar>\s+\d+\s*\(.*?\)))\s*;', re.S)


def seed_temperatures(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if solved_times(target):
        raise ValueError('Target already contains solved times')
    if any(target.glob('processor[0-9]*')):
        raise ValueError('Seed before decomposition')
    source_settings = json.loads((source / 'settings.json').read_text())
    target_settings = json.loads((target / 'settings.json').read_text())
    for key in ('inlet_temperature_K', 'heat_flux_W_m2'):
        if source_settings[key] != target_settings[key]:
            raise ValueError('Temperature boundary conditions differ: ' + key)
    latest = latest_time(source)
    if latest is None or float(latest.name) <= 0:
        raise ValueError('No solved temperature available')
    for region in ('fluid', 'solid'):
        for name in ('points', 'faces', 'owner', 'neighbour', 'boundary'):
            if (source / f'constant/{region}/polyMesh/{name}').read_bytes() != (target / f'constant/{region}/polyMesh/{name}').read_bytes():
                raise ValueError(f'Warm-start mesh differs: {region}/{name}')
    payloads = {}
    for region in ('fluid', 'solid'):
        match = INTERNAL.search((latest / region / 'T').read_text())
        if not match:
            raise ValueError('Unsupported saved T encoding')
        values = parse_values(match.group(1))
        if not values or any(not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError('Invalid initial temperature')
        if region == 'fluid' and target_settings.get('transport_polynomials') is not None:
            fit = target_settings['transport_polynomials']
            if min(values) < fit['Tmin_K'] or max(values) > fit['Tmax_K']:
                raise ValueError('Warm-start fluid temperature outside target transport fit range')
        if len(values) > 1:
            owner = (source / f'constant/{region}/polyMesh/owner').read_text()
            neighbour = (source / f'constant/{region}/polyMesh/neighbour').read_text()
            cells = 1 + max(int(v) for text in (owner, neighbour) for v in re.findall(r'\b\d+\b', text.split('(', 1)[1].rsplit(')', 1)[0]))
            if len(values) != cells:
                raise ValueError('Temperature size differs from mesh cells')
        if (target / 'initial-temperature-original' / region / 'T').exists():
            raise ValueError('Target already seeded')
        if not INTERNAL.search((target / '0' / region / 'T').read_text()):
            raise ValueError('Unsupported target T encoding')
        payloads[region] = match.group(0)
    records = {}
    for region in ('fluid', 'solid'):
        src, dst = latest / region / 'T', target / '0' / region / 'T'
        backup = target / 'initial-temperature-original' / region / 'T'
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(dst.read_bytes())
        dst.write_text(INTERNAL.sub(lambda _: payloads[region], dst.read_text(), count=1))
        records[region] = {'source': str(src), 'sha256': digest(src)}
    manifest_path = target / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['temperature_initialization'] = {'source_case': str(source), 'source_iteration': latest.name, 'fields': records,
                                              'selection': 'internalField only; target boundary conditions retained'}
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    print(json.dumps(seed_temperatures(args.source, args.target), indent=2))


if __name__ == '__main__':
    main()
