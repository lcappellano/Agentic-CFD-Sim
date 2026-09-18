"""Named material library and material-basis construction.

A material basis is the JSON the CFD builder consumes: ``fluid_properties`` at
the inlet temperature, ``solid_properties``, and optionally fitted
``transport_polynomials``. Agents choose names; the code supplies numbers and
their sources. Extend :data:`SOLIDS` (with a source) rather than writing
run-local property scripts.
"""
import re

from src.thermal.liquid_water import properties as water_properties

SOLIDS = {
    'copper': {
        'density_kg_m3': 8920., 'cp_J_kg_K': 394., 'conductivity_W_m_K': 394.,
        'molecular_weight': 63.546, 'aliases': ['cu', 'c101', 'c110', 'ofhc', 'ofhc copper', 'cu-etp', 'copper etp'],
        'source': 'KME Cu-ETP datasheet 2021 (rolled copper, room temperature)',
        'limits': 'Constant properties; conductivity falls ~15% by 500 K.'},
    'aluminum_6061': {
        'density_kg_m3': 2700., 'cp_J_kg_K': 896., 'conductivity_W_m_K': 167.,
        'molecular_weight': 26.98, 'aliases': ['aluminium', 'aluminum', 'al', '6061', 'al6061', 'al 6061', 'aluminum 6061', 'aluminium 6061', '6061-t6'],
        'source': 'ASM Aerospace Specification Metals, 6061-T6 (room temperature)',
        'limits': 'Constant properties; T6 temper.'},
    'stainless_316': {
        'density_kg_m3': 8000., 'cp_J_kg_K': 500., 'conductivity_W_m_K': 16.3,
        'molecular_weight': 55.85, 'aliases': ['stainless', 'stainless steel', '316', '316l', 'ss316', 'ss'],
        'source': 'AK Steel 316/316L product data bulletin (room temperature)',
        'limits': 'Constant properties.'},
}

FLUIDS = {
    'water': {'aliases': ['h2o', 'liquid water', 'deionized water', 'di water', 'coolant water'],
              'molecular_weight': 18.015,
              'source': 'IAPWS SR6-08(2011) liquid water at 0.1 MPa (src/thermal/liquid_water.py)',
              'limits': 'Reference properties at 0.1 MPa; 273.15-383.15 K.'},
}


def _normalise(name):
    return re.sub(r'[\s_-]+', ' ', str(name).strip().lower())


def _lookup(library, name, kind):
    key = _normalise(name)
    for canonical, entry in library.items():
        if key in (_normalise(canonical), *[_normalise(a) for a in entry['aliases']]):
            return canonical
    raise ValueError(f'Unknown {kind} material {name!r}; known names: {sorted(library)}')


def solid_name(name):
    return _lookup(SOLIDS, name, 'solid')


def fluid_name(name):
    return _lookup(FLUIDS, name, 'fluid')


def material_basis(solid, fluid, inlet_temperature_K, transport='constant',
                   fit_range_K=None, reference_pressure_Pa=None):
    """Build the material basis consumed by the CFD builder and screens."""
    solid_key, fluid_key = solid_name(solid), fluid_name(fluid)
    solid_entry = SOLIDS[solid_key]
    liquid = water_properties(inlet_temperature_K)
    basis = {
        'schema_version': 2,
        'solid': solid_key, 'fluid': fluid_key,
        'reference_temperature_K': inlet_temperature_K,
        'reference_pressure_Pa': 100000,
        'fluid_properties': {**liquid, 'molecular_weight': FLUIDS[fluid_key]['molecular_weight']},
        'solid_properties': {k: solid_entry[k] for k in ('density_kg_m3', 'cp_J_kg_K', 'conductivity_W_m_K', 'molecular_weight')},
        'transport_model': 'constant',
        'sources': [FLUIDS[fluid_key]['source'], solid_entry['source']],
        'limitations': [FLUIDS[fluid_key]['limits'], solid_entry['limits'],
                        'Density and heat capacity are constant at the inlet reference state.'],
    }
    if transport == 'polynomial':
        from src.thermal.fit_water_transport import fit_transport
        if fit_range_K is None or reference_pressure_Pa is None:
            raise ValueError('Polynomial transport needs fit_range_K and reference_pressure_Pa')
        basis = fit_transport(basis, fit_range_K[0], fit_range_K[1], reference_pressure_Pa)
    elif transport != 'constant':
        raise ValueError('transport must be constant or polynomial')
    return basis
