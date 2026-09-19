"""Diagnostic summary of the latest saved fields and monitors of a case.

Port conduction uses the saved boundary ``gradT`` so it is geometry independent.
The result is evidence for the gates in ``run_bounded``; it grants nothing.
"""
import argparse
import json
import math
from pathlib import Path

from src.cfd.transport import conductivity_values
from src.foam.fields import PolyMesh, latest_time
from src.foam.monitors import monitor_rows, window_range, field_min_max

MONITOR_NAMES = ['inletPressure', 'outletPressure', 'inletMass', 'outletMass', 'inletTemperature',
                 'outletTemperature', 'heatedMax', 'wettedMax', 'heatedPower', 'interfacePower', 'fluidPower']


def hottest_heated_face(solid, latest):
    values = solid.read_boundary(latest / 'solid/T', 'heated')
    index = max(range(len(values)), key=values.__getitem__)
    face = solid.patch_range('heated')[index]
    return {'temperature_K': values[index], 'coordinate_m': solid.face_centre(face),
            'location_kind': 'hottest heated boundary face centroid', 'global_face_index': face}


def yplus_review(fluid, values):
    areas = fluid.patch_areas('fluid_to_solid')
    if len(areas) != len(values):
        raise ValueError('yPlus face count does not match the wall patch')
    low = [i for i, v in enumerate(values) if v < 30]
    centres = fluid.patch_centres('fluid_to_solid')
    return {'min': min(values), 'max': max(values), 'mean': sum(values) / len(values),
            'fraction_below30': len(low) / len(values), 'fraction_above300': sum(v > 300 for v in values) / len(values),
            'area_fraction_below30': sum(areas[i] for i in low) / sum(areas),
            'minimum_location_m': centres[min(range(len(values)), key=values.__getitem__)]}


def summarize(case, window=100):
    case = Path(case).resolve()
    settings = json.loads((case / 'settings.json').read_text())
    latest = latest_time(case)
    if latest is None or float(latest.name) <= 0:
        raise ValueError('No solved time directory')
    histories = {name: monitor_rows(case, name) for name in MONITOR_NAMES}
    if any(not rows or rows[-1][0] != float(latest.name) for rows in histories.values()):
        raise ValueError('Monitor history and saved field times are inconsistent')
    last = {name: rows[-1][1][0] for name, rows in histories.items()}
    fluid = PolyMesh(case / 'constant/fluid/polyMesh')
    solid = PolyMesh(case / 'constant/solid/polyMesh')
    cp, tin, rho = settings['cp_J_kg_K'], settings['inlet_temperature_K'], settings['rho_kg_m3']
    ports = {}
    port_temperatures = []
    for patch in ('inlet', 'outlet'):
        phi = fluid.read_boundary(latest / 'fluid/phi', patch)
        u = fluid.read_boundary(latest / 'fluid/U', patch)
        t = fluid.read_boundary(latest / 'fluid/T', patch)
        p = fluid.read_boundary(latest / 'fluid/p', patch)
        port_temperatures.extend(t)
        mass = sum(phi)
        info = {'signed_outward_mass_kg_s': mass,
                'mass_weighted_total_pressure_Pa': sum(f * (pr + .5 * rho * sum(x * x for x in vel)) for f, pr, vel in zip(phi, p, u)) / mass,
                'advective_heat_W': sum(f * cp * (v - tin) for f, v in zip(phi, t)),
                'kinetic_energy_flux_W': sum(f * .5 * sum(x * x for x in vel) for f, vel in zip(phi, u)),
                'diffusive_heat_into_fluid_W': None, 'conductivity_range_W_m_K': None}
        if (latest / 'fluid/gradT').is_file():
            gradients = fluid.read_boundary(latest / 'fluid/gradT', patch)
            alphat = (fluid.read_boundary(latest / 'fluid/alphat', patch) if (latest / 'fluid/alphat').is_file()
                      else [0.] * len(gradients))  # laminar: no turbulent diffusivity
            try:
                k = conductivity_values(settings, t)
                info['conductivity_range_W_m_K'] = [min(k), max(k)]
                info['diffusive_heat_into_fluid_W'] = sum((kk + cp * a) * sum(g * s for g, s in zip(grad, area))
                                                          for kk, a, grad, area in zip(k, alphat, gradients, fluid.patch_area_vectors(patch)))
            except ValueError as error:
                info['diffusion_error'] = str(error)
        ports[patch] = info
    heat = sum(v['advective_heat_W'] for v in ports.values())
    energy = heat + sum(v['kinetic_energy_flux_W'] for v in ports.values())
    diffusion = [v['diffusive_heat_into_fluid_W'] for v in ports.values()]
    wall_t = fluid.read_boundary(latest / 'fluid/T', 'fluid_to_solid')
    wall_p = fluid.read_boundary(latest / 'fluid/p', 'fluid_to_solid')
    yplus = fluid.read_boundary(latest / 'fluid/yPlus', 'fluid_to_solid') if (latest / 'fluid/yPlus').is_file() else None
    heated_power = last['heatedPower']
    out = {
        'case': str(case), 'latest_fields': latest.name, 'monitor_last': last, 'ports': ports,
        'sensible_heat_pickup_W': heat, 'modeled_advected_energy_pickup_W': energy,
        'pressure_drop_Pa': last['inletPressure'] - last['outletPressure'],
        'total_pressure_drop_Pa': ports['inlet']['mass_weighted_total_pressure_Pa'] - ports['outlet']['mass_weighted_total_pressure_Pa'],
        'mass_weighted_port_total_pressure_Pa': {k: v['mass_weighted_total_pressure_Pa'] for k, v in ports.items()},
        'mass_imbalance_fraction': abs(last['inletMass'] + last['outletMass']) / abs(last['inletMass']),
        'energy_imbalance_without_port_diffusion_fraction': abs(energy - heated_power) / abs(heated_power),
        'energy_imbalance_with_port_diffusion_fraction': (abs(energy - heated_power - sum(diffusion)) / abs(heated_power)
                                                          if all(v is not None for v in diffusion) else None),
        'heated_maximum_location': hottest_heated_face(solid, latest),
        'maximum_wetted_temperature_K': max(wall_t),
        'minimum_wetted_absolute_pressure_Pa': min(wall_p),
        'nonpositive_wetted_pressure_face_count': sum(p <= 0 for p in wall_p),
        'yplus': yplus_review(fluid, yplus) if yplus else {'status': 'not written', 'note': 'laminar case or yPlus function object absent'},
        'final_window_ranges': {name: window_range(rows, float(latest.name), window) for name, rows in histories.items()},
        'window_iterations': window,
    }
    minmax = field_min_max(case, 'fluid', 'p')
    if minmax:
        out['minimum_absolute_pressure_Pa'] = minmax[1]
        out['minimum_pressure_location_m'] = minmax[2]
    spec = settings.get('transport_polynomials')
    if spec is not None:
        temperatures = fluid.read_internal(latest / 'fluid/T') + wall_t + port_temperatures
        low, high = min(temperatures), max(temperatures)
        out['transport_validity'] = {'model': 'polynomial', 'declared_Tmin_K': spec['Tmin_K'], 'declared_Tmax_K': spec['Tmax_K'],
                                     'observed_fluid_Tmin_K': low, 'observed_fluid_Tmax_K': high,
                                     'within_declared_range': spec['Tmin_K'] <= low and high <= spec['Tmax_K']}
    else:
        out['transport_validity'] = {'model': 'constant', 'within_declared_range': None}
    (case / 'summary.json').write_text(json.dumps(out, indent=2) + '\n')
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.case), indent=2))


if __name__ == '__main__':
    main()
