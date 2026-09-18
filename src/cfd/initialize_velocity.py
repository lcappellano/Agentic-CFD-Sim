"""Potential-flow velocity initialisation for a fresh case (U only).

``potentialFoam`` writes only U: no phi (its volumetric flux would conflict
with the CHT mass flux) and no pressure. Every other initial field must be
byte-identical afterwards, and the inlet mass flow is re-checked.
"""
import argparse
import json
from pathlib import Path
import re

from src.foam.environment import run_tool
from src.foam.fields import PolyMesh
from src.foam.hashing import digest


def initialize(case):
    case = Path(case).resolve()
    folder = case / 'initialization'
    if folder.exists() or any(case.glob('processor[0-9]*')):
        raise ValueError('Initialize a fresh, undecomposed case only')
    if (case / '0/fluid/phi').exists():
        raise ValueError('Unexpected pre-existing phi; mass/volume flux conventions must not mix')
    before = {str(p.relative_to(case)): p.read_bytes() for p in (case / '0').rglob('*') if p.is_file()}
    folder.mkdir()
    (folder / 'U-before').write_bytes(before['0/fluid/U'])
    solution = case / 'system/fluid/fvSolution'
    text = re.sub(r'\bsolvers\s*\{', 'solvers { Phi { solver GAMG; tolerance 1e-11; relTol 0; smoother GaussSeidel; }',
                  solution.read_text(), count=1)
    solution.write_text(text + '\npotentialFlow { nNonOrthogonalCorrectors 10; }\n')
    command = ['potentialFoam', '-case', str(case), '-region', 'fluid', '-initialiseUBCs']
    result = run_tool(command, case, folder / 'log.potentialFoam', check=False)
    record = {'command': command, 'exit_code': result.returncode, 'changed_field': 'U only',
              'original_U_sha256': digest(folder / 'U-before')}
    (folder / 'record.json').write_text(json.dumps(record, indent=2) + '\n')
    if result.returncode != 0:
        raise RuntimeError('potentialFoam failed; see ' + str(folder / 'log.potentialFoam'))
    after = {str(p.relative_to(case)): p.read_bytes() for p in (case / '0').rglob('*') if p.is_file()}
    if set(after) != set(before) or any(after[k] != v for k, v in before.items() if k != '0/fluid/U'):
        raise ValueError('Potential initialization modified a field other than U')
    settings = json.loads((case / 'settings.json').read_text())
    mesh = PolyMesh(case / 'constant/fluid/polyMesh')
    u = mesh.read_boundary(case / '0/fluid/U', 'inlet')
    mass = -settings['rho_kg_m3'] * sum(sum(v * a for v, a in zip(vel, area)) for vel, area in zip(u, mesh.patch_area_vectors('inlet')))
    if mass <= 0 or abs(mass / settings['mass_flow_kg_s'] - 1) > 1e-6:
        raise ValueError('Potential initialization inlet mass flow or direction mismatch')
    record.update(initialized_U_sha256=digest(case / '0/fluid/U'), inlet_mass_flow_kg_s=mass)
    (folder / 'record.json').write_text(json.dumps(record, indent=2) + '\n')
    manifest_path = case / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['velocity_initialization'] = record
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    args = parser.parse_args()
    print(json.dumps(initialize(args.case), indent=2))


if __name__ == '__main__':
    main()
