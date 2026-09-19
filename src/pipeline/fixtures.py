"""Synthetic, unapproved handoff from the through-bore block fixture (tests only)."""
import json
from pathlib import Path
import shutil

from src.foam.hashing import digest

FIXTURES = Path(__file__).resolve().parents[1] / 'cad' / 'fixtures'


def synthetic_handoff(destination, solid='copper', fluid='water', pressure_bounds=(111325, 111325), flow_bounds=None):
    """Unapproved fixture handoff; ``pressure_bounds``/``flow_bounds`` None leaves the review blank (autofill)."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / 'cooling_block_through_bore_v1.step', destination / 'source.step')
    shutil.copyfile(FIXTURES / 'cooling_block_through_bore_v1.preview.json', destination / 'model.json')
    model = json.loads((destination / 'model.json').read_text())
    if model['source']['sha256'] != digest(destination / 'source.step'):
        raise ValueError('Fixture preview does not match the fixture STEP')
    ports = sorted(model['virtual_faces'], key=lambda v: v['centroid_mm'][0])
    heated = max(model['faces'], key=lambda f: f['centroid_mm'][2])
    requirements = {'schema_version': 1, 'revision': 1, 'model_fingerprint': model['import_fingerprint'],
                    'selections': {'inlet': [ports[0]['id']], 'outlet': [ports[1]['id']], 'heated': [heated['id']]},
                    'requirements': {'solid_material': solid, 'coolant_material': fluid, 'inlet_temperature_K': 300,
                                     'maximum_surface_temperature_K': 500, 'heat_load': {'mode': 'heat_flux_W_m2', 'value': 100000},
                                     'outlet_absolute_pressure_bounds_Pa': list(pressure_bounds) if pressure_bounds else [None, None],
                                     'mass_flow_bounds_kg_s': list(flow_bounds) if flow_bounds else [None, None], 'units_confirmed': True,
                                     'notes': 'SYNTHETIC FIXTURE; not a user approval'}}
    (destination / 'requirements.json').write_text(json.dumps(requirements, indent=2) + '\n')
    return destination
