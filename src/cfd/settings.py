"""Derive complete case settings from an operating point, geometry and materials.

Agents supply the operating point in the units they have (L/min or kg/s,
W/m² or W, K or °C) plus a numerics profile. Everything geometric (inlet area,
direction, hydraulic diameter) and everything property-derived (mass flow,
turbulence scales) is computed here from the geometry manifest and basis.
"""
import math

SOLVER = 'OpenCFD v2412 chtMultiRegionSimpleFoam'


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be a positive finite number')
    return float(value)


def temperature_K(operating, key):
    if operating.get(key + '_K') is not None:
        return _positive(operating[key + '_K'], key + '_K')
    if operating.get(key + '_C') is not None:
        return _positive(operating[key + '_C'] + 273.15, key + '_C')
    raise ValueError(f'Provide {key}_K or {key}_C')


def pressure_Pa(operating, key):
    if operating.get(key + '_Pa') is not None:
        return _positive(operating[key + '_Pa'], key + '_Pa')
    if operating.get(key + '_bar') is not None:
        return _positive(operating[key + '_bar'] * 1e5, key + '_bar')
    return None


def case_settings(operating, geometry, basis, numerics, iterations):
    """Return the complete settings dictionary consumed by ``cht_case.build``."""
    fluid = basis['fluid_properties']
    rho = fluid['density_kg_m3']
    inlet = geometry['boundary_map']['inlet']
    inlet_area = inlet['area_m2']
    outward = geometry['port_outward_normals']['inlet']
    norm = math.sqrt(sum(v * v for v in outward))
    direction = [-v / norm for v in outward]
    diameter = geometry['port_hydraulic_diameter_m']['inlet']
    settings = {
        'inlet_temperature_K': temperature_K(operating, 'inlet_temperature'),
        'outlet_absolute_pressure_Pa': pressure_Pa(operating, 'outlet_absolute_pressure'),
        'temperature_limit_K': temperature_K(operating, 'temperature_limit'),
    }
    if settings['outlet_absolute_pressure_Pa'] is None:
        raise ValueError('Provide outlet_absolute_pressure_Pa or outlet_absolute_pressure_bar')
    if operating.get('mass_flow_kg_s') is not None:
        settings['mass_flow_kg_s'] = _positive(operating['mass_flow_kg_s'], 'mass_flow_kg_s')
        settings['volume_flow_L_min'] = settings['mass_flow_kg_s'] / rho * 60000
    elif operating.get('volume_flow_L_min') is not None:
        settings['volume_flow_L_min'] = _positive(operating['volume_flow_L_min'], 'volume_flow_L_min')
        settings['mass_flow_kg_s'] = rho * settings['volume_flow_L_min'] / 60000
    else:
        raise ValueError('Provide mass_flow_kg_s or volume_flow_L_min')
    if operating.get('heat_flux_W_m2') is not None:
        settings['heat_flux_W_m2'] = _positive(operating['heat_flux_W_m2'], 'heat_flux_W_m2')
    elif operating.get('total_heat_load_W') is not None:
        settings['heat_flux_W_m2'] = _positive(operating['total_heat_load_W'], 'total_heat_load_W') / geometry['heated_area_m2']
    else:
        raise ValueError('Provide heat_flux_W_m2 or total_heat_load_W')
    settings['total_heat_load_W'] = settings['heat_flux_W_m2'] * geometry['heated_area_m2']
    for key in ('max_pump_pressure_rise_Pa', 'target_pump_pressure_rise_Pa'):
        if operating.get(key) is not None:
            settings[key] = _positive(operating[key], key)
    settings['minimum_saturation_margin_K'] = float(operating.get('minimum_saturation_margin_K', 10))
    settings.update({
        'inlet_area_m2': inlet_area, 'inlet_direction': direction, 'hydraulic_diameter_m': diameter,
        'heated_area_m2': geometry['heated_area_m2'],
        'inlet_speed_m_s': settings['mass_flow_kg_s'] / (rho * inlet_area),
        'turbulence_length_scale_m': .07 * diameter,
        'rho_kg_m3': rho, 'cp_J_kg_K': fluid['cp_J_kg_K'], 'mu_Pa_s': fluid['dynamic_viscosity_Pa_s'],
        'k_W_m_K': fluid['conductivity_W_m_K'],
        'solid_material': basis.get('solid'), 'fluid_material': basis.get('fluid'),
        'transport_model': basis.get('transport_model', 'constant'),
        'transport_polynomials': basis.get('transport_polynomials'),
        'density_and_cp_model': 'constant at the inlet reference state',
        'solver': SOLVER, 'gravity_m_s2': [0, 0, 0], 'iterations': int(iterations),
        'unheated_exterior': 'adiabatic', 'radiation': 'none',
    })
    settings['numerics_profile'] = numerics.get('name')
    for key, value in numerics.items():
        if key not in ('name', 'description'):
            settings[key] = value
    if settings['inlet_temperature_K'] >= settings['temperature_limit_K']:
        raise ValueError('temperature_limit must exceed inlet temperature')
    return settings
