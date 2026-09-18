"""Simulation spec: the single input an agent writes for a new case.

Minimal example (everything else has a default or comes from the handoff)::

    {"schema_version": 1,
     "handoff": "runs/<review>/handoffs/revision-6-xxxx",
     "operating": {"volume_flow_L_min": 40, "outlet_absolute_pressure_bar": 8},
     "numerics": {"profile": "tet-robust"},
     "schedule": {"maximum": 2000}}

See docs/pipeline.md for every key.
"""
import copy
import json
import os
from pathlib import Path

PROFILE_DIR = Path(__file__).resolve().parent / 'profiles'
TOP_KEYS = {'schema_version', 'handoff', 'label', 'operating', 'materials', 'mesh', 'numerics', 'acceptance',
            'schedule', 'initialization', 'unapproved_handoff_ok', 'notes'}
OPERATING_KEYS = {'inlet_temperature_K', 'inlet_temperature_C', 'outlet_absolute_pressure_Pa', 'outlet_absolute_pressure_bar',
                  'volume_flow_L_min', 'mass_flow_kg_s', 'heat_flux_W_m2', 'total_heat_load_W', 'temperature_limit_K',
                  'temperature_limit_C', 'max_pump_pressure_rise_Pa', 'target_pump_pressure_rise_Pa', 'minimum_saturation_margin_K'}
MATERIAL_KEYS = {'solid', 'fluid', 'transport', 'fit_range_K', 'reference_pressure_Pa'}
SCHEDULE_DEFAULTS = {'initial': 100, 'chunk': 500, 'maximum': 2000, 'ranks': None}
DEFAULT_PROFILES = {'mesh': 'tet-coarse', 'numerics': 'tet-robust', 'acceptance': 'project-screening'}


def load_profiles(kind):
    return json.loads((PROFILE_DIR / f'{kind}.json').read_text())['profiles']


def profile(kind, name, overrides=None):
    profiles = load_profiles(kind)
    if name not in profiles:
        raise ValueError(f'Unknown {kind} profile {name!r}; available: {sorted(profiles)}')
    result = copy.deepcopy(profiles[name])
    unknown = set(overrides or {}) - set(result) - ({'refinement_boxes', 'wall_size_m', 'bulk_size_m', 'transition_distance_m', 'keep_interface_group'} if kind == 'mesh' else set())
    if unknown:
        raise ValueError(f'Unknown {kind} override keys {sorted(unknown)}; profile keys are {sorted(result)}')
    result.update(overrides or {})
    result['name'] = name
    return result


def _section(spec, key, allowed):
    section = spec.get(key) or {}
    if not isinstance(section, dict):
        raise ValueError(f'{key} must be an object')
    unknown = set(section) - allowed
    if unknown:
        raise ValueError(f'Unknown {key} keys: {sorted(unknown)}')
    return dict(section)


def load(path):
    spec = json.loads(Path(path).read_text())
    if not isinstance(spec, dict) or spec.get('schema_version') != 1:
        raise ValueError('Spec must be a JSON object with schema_version 1')
    unknown = set(spec) - TOP_KEYS
    if unknown:
        raise ValueError(f'Unknown spec keys: {sorted(unknown)}')
    if not isinstance(spec.get('handoff'), str):
        raise ValueError('spec.handoff must be a handoff directory path')
    return spec


def resolve(spec, root):
    """Merge the spec with handoff defaults and profiles into explicit settings."""
    root = Path(root).resolve()
    handoff = (root / spec['handoff']).resolve()
    if not handoff.is_dir() or not (handoff / 'requirements.json').is_file():
        raise ValueError(f'Handoff directory not found: {handoff}')
    requirements = json.loads((handoff / 'requirements.json').read_text())['requirements']
    project = json.loads((handoff / 'project.json').read_text()) if (handoff / 'project.json').is_file() else {}
    operating = _section(spec, 'operating', OPERATING_KEYS)
    defaults = {}
    if requirements.get('inlet_temperature_K') is not None:
        defaults['inlet_temperature_K'] = requirements['inlet_temperature_K']
    if requirements.get('maximum_surface_temperature_K') is not None:
        defaults['temperature_limit_K'] = requirements['maximum_surface_temperature_K']
    load = requirements.get('heat_load') or {}
    if load.get('value') is not None:
        defaults[load['mode']] = load['value']
    bounds = requirements.get('outlet_absolute_pressure_bounds_Pa') or [None, None]
    if bounds[0] is not None and bounds[0] == bounds[1]:
        defaults['outlet_absolute_pressure_Pa'] = bounds[0]
    if requirements.get('max_pump_pressure_rise_Pa') is not None:
        defaults['max_pump_pressure_rise_Pa'] = requirements['max_pump_pressure_rise_Pa']
    for key, value in defaults.items():
        family = key.rsplit('_', 1)[0]
        if not any(k.startswith(family) for k in operating):
            operating[key] = value
    materials = _section(spec, 'materials', MATERIAL_KEYS)
    materials.setdefault('solid', requirements.get('solid_material') or project.get('solid_material'))
    materials.setdefault('fluid', requirements.get('coolant_material') or project.get('coolant_material') or 'water')
    materials.setdefault('transport', 'constant')
    if not materials['solid']:
        raise ValueError('materials.solid is required (handoff has no solid_material)')
    sections = {}
    for kind in ('mesh', 'numerics', 'acceptance'):
        section = _section(spec, kind, {'profile', 'overrides'})
        sections[kind] = profile(kind, section.get('profile', DEFAULT_PROFILES[kind]), section.get('overrides'))
    schedule = {**SCHEDULE_DEFAULTS, **_section(spec, 'schedule', set(SCHEDULE_DEFAULTS))}
    if schedule['ranks'] is None:
        schedule['ranks'] = max(1, min(4, (os.cpu_count() or 1) // 2))
    if not 0 < schedule['initial'] <= schedule['maximum'] or schedule['chunk'] <= 0 or schedule['ranks'] < 1:
        raise ValueError('schedule requires 0 < initial <= maximum, chunk > 0, ranks >= 1')
    initialization = _section(spec, 'initialization', {'temperature_from_case'})
    return {'handoff': handoff, 'label': spec.get('label') or handoff.parent.parent.name[:40], 'operating': operating,
            'materials': materials, 'mesh': sections['mesh'], 'numerics': sections['numerics'],
            'acceptance': sections['acceptance'], 'schedule': schedule, 'initialization': initialization,
            'unapproved_handoff_ok': bool(spec.get('unapproved_handoff_ok', False)), 'notes': spec.get('notes')}


def describe(resolved):
    """Compact, JSON-safe view of a resolved spec for state.json and dry runs."""
    view = copy.deepcopy({k: v for k, v in resolved.items() if k != 'handoff'})
    view['handoff'] = str(resolved['handoff'])
    return view
