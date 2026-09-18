"""Bulk liquid energy-balance screen for candidate flows (analytical, not CFD)."""
import argparse
import json
import math
from pathlib import Path

from src.foam.hashing import digest
from src.thermal.saturation import saturation_temperature


def screen(project, geometry, basis, flows_L_min, margin_K=10):
    fluid = basis['fluid_properties']
    rho, cp = fluid['density_kg_m3'], fluid['cp_J_kg_K']
    temperature = project['inlet_temperature_K']
    area = geometry['heated_area_m2']
    flux = project.get('heat_flux_W_m2')
    power = flux * area if flux is not None else project['total_heat_load_W']
    outlet_pressure = project['outlet_absolute_pressure_bounds_Pa'][0]
    sat = saturation_temperature(outlet_pressure)
    port_area = geometry['boundary_map']['inlet']['area_m2']
    diameter = geometry['port_hydraulic_diameter_m']['inlet']
    if any(not math.isfinite(v) or v <= 0 for v in (rho, cp, temperature, area, power, port_area, diameter)):
        raise ValueError('Positive finite SI physical inputs required')
    rows = []
    for flow in flows_L_min:
        if not math.isfinite(flow) or flow <= 0:
            raise ValueError('Volume flow must be positive in L/min')
        volume_rate = flow / 60000
        mass = rho * volume_rate
        speed = volume_rate / port_area
        outlet = temperature + power / (mass * cp)
        rows.append({'flow_L_min': flow, 'mass_flow_kg_s': mass, 'port_speed_m_s': speed,
                     'port_Reynolds': rho * speed * diameter / fluid['dynamic_viscosity_Pa_s'],
                     'bulk_outlet_heat_balance_K': outlet,
                     'bulk_saturation_margin_K': sat - outlet,
                     'bulk_single_phase_screen_pass': outlet + margin_K < sat})
    return {'status': 'analytical_screen', 'heat_input_W': power,
            'inlet_density_conversion_kg_m3': rho, 'saturation_margin_K': margin_K,
            'outlet_saturation_temperature_K': sat, 'cases': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project', 'geometry', 'properties', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--flows', nargs='+', type=float, required=True, help='L/min')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Use a fresh output file to preserve prior evidence')
    paths = (args.project, args.geometry, args.properties)
    result = screen(*(json.loads(p.read_text()) for p in paths), args.flows)
    result['input_sha256'] = {str(p): digest(p) for p in (*paths, Path(__file__))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
