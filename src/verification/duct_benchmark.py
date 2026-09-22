"""Known-result check for a straight passage: developed friction and local Nusselt number from a solved case
against the experimental smooth-duct correlations (Petukhov or 64/Re; Gnielinski or 4.36).

The developed pressure gradient is a linear fit of station-averaged static pressure over the middle of the
passage (entry and exit excluded); the local Nusselt number uses the interface wall heat flux and wall
temperature per station and the flux-weighted bulk temperature of the same station. Correlations are fits of
measurements, so this is an independent check of the solver, mesh and wall treatment, not of the correlations.
"""
import argparse
import json
import math
from pathlib import Path
import re

import numpy as np

from src.foam.environment import run_tool
from src.foam.fields import PolyMesh, latest_time
from src.thermal.prescreen import friction_factor, nusselt

AXES = {'x': 0, 'y': 1, 'z': 2}


def _scalar(path):
    text = Path(path).read_text(errors='ignore').split('internalField', 1)[1]
    count = int(re.search(r'List<scalar>\s+(\d+)', text).group(1))
    return np.fromstring(text[text.index('(') + 1:], sep='\n', count=count)


def _vector(path):
    text = Path(path).read_text(errors='ignore').split('internalField', 1)[1]
    count = int(re.search(r'List<vector>\s+(\d+)', text).group(1))
    start = text.index('(') + 1
    return np.fromstring(text[start:text.index('\n)\n', start)].replace('(', ' ').replace(')', ' '), sep=' ').reshape(-1, 3)[:count]


def developed_friction(positions, pressures, rho, speed, diameter, window=(0.4, 0.8)):
    """Darcy friction factor from the pressure gradient fitted over ``window`` (fractions of the length)."""
    positions, pressures = np.asarray(positions, float), np.asarray(pressures, float)
    lo = positions.min() + window[0] * (positions.max() - positions.min())
    hi = positions.min() + window[1] * (positions.max() - positions.min())
    mask = (positions >= lo) & (positions <= hi)
    if mask.sum() < 3:
        raise ValueError('Too few stations inside the developed window')
    slope = np.polyfit(positions[mask], pressures[mask], 1)[0]
    gradient = -slope  # pressure falls along the flow
    return gradient * diameter / (0.5 * rho * speed ** 2), gradient, (lo, hi)


def nusselt_from_bins(wall_positions, wall_flux, wall_temperature, wall_area, bulk_positions, bulk_temperature,
                      diameter, conductivity, edges):
    """Local Nusselt number per bin from area-weighted wall flux and temperature and the bin's bulk temperature."""
    rows = []
    wall_positions, wall_flux, wall_temperature, wall_area = (np.asarray(a, float) for a in (wall_positions, wall_flux, wall_temperature, wall_area))
    bulk_positions, bulk_temperature = np.asarray(bulk_positions, float), np.asarray(bulk_temperature, float)
    for a, b in zip(edges[:-1], edges[1:]):
        w = (wall_positions >= a) & (wall_positions < b)
        k = (bulk_positions >= a) & (bulk_positions < b)
        if not w.any() or not k.any():
            continue
        area = wall_area[w].sum()
        q = np.sum(wall_flux[w] * wall_area[w]) / area
        tw = np.sum(wall_temperature[w] * wall_area[w]) / area
        tb = bulk_temperature[k].mean()
        h = q / (tw - tb) if tw != tb else float('nan')
        rows.append({'position_m': 0.5 * (a + b), 'wall_flux_W_m2': q, 'wall_temperature_K': tw, 'bulk_temperature_K': tb,
                     'h_W_m2_K': h, 'nusselt': h * diameter / conductivity})
    return rows


def run(case, time=None, axis='x', diameter=None, window=(0.4, 0.8), bins=40, output=None):
    case = Path(case).resolve()
    settings = json.loads((case / 'settings.json').read_text())
    latest = Path(time) if time else latest_time(case)
    latest = case / latest.name if not Path(latest).is_absolute() else latest
    fluid = latest / 'fluid'
    for name, func in (('Cx', 'writeCellCentres'), ('V', 'writeCellVolumes')):
        if not (fluid / name).exists():
            run_tool(['postProcess', '-func', func, '-region', 'fluid', '-time', latest.name, '-case', str(case)],
                     case, case / f'log.postProcess.{func}', check=False)
    ax = AXES[axis]
    centres = np.stack([_scalar(fluid / n) for n in ('Cx', 'Cy', 'Cz')], axis=1)
    volumes, pressure, temperature = _scalar(fluid / 'V'), _scalar(fluid / 'p'), _scalar(fluid / 'T')
    velocity = _vector(fluid / 'U')
    rho, mu, k, cp = settings['rho_kg_m3'], settings['mu_Pa_s'], settings['k_W_m_K'], settings['cp_J_kg_K']
    diameter = diameter or settings['hydraulic_diameter_m']
    area = math.pi * (0.5 * diameter) ** 2
    speed = settings['mass_flow_kg_s'] / (rho * area)
    reynolds, prandtl = rho * speed * diameter / mu, cp * mu / k
    positions = centres[:, ax]
    edges = np.linspace(positions.min(), positions.max(), bins + 1)
    station_x, station_p, station_tb, station_u = [], [], [], []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (positions >= a) & (positions < b)
        if m.sum() < 5:
            continue
        w = volumes[m] / volumes[m].sum()
        flux = np.abs(velocity[m, ax]) * volumes[m]
        station_x.append(0.5 * (a + b)); station_p.append(np.sum(w * pressure[m]))
        station_tb.append(np.sum(flux * temperature[m]) / flux.sum()); station_u.append(np.sum(w * np.linalg.norm(velocity[m], axis=1)))
    f_cfd, gradient, (lo, hi) = developed_friction(station_x, station_p, rho, speed, diameter, window)
    f_ref, regime = friction_factor(reynolds)
    blasius = 0.316 * reynolds ** -0.25 if reynolds >= 2300 else None
    # wall side: interface patch values of wallHeatFlux and T, face centres and areas
    mesh = PolyMesh(case / 'constant/fluid/polyMesh')
    patch = 'fluid_to_solid'
    q = np.array(mesh.read_boundary(latest / 'fluid/wallHeatFlux', patch), float)
    tw = np.array(mesh.read_boundary(latest / 'fluid/T', patch), float)
    faces_x = np.array([c[ax] for c in mesh.patch_centres(patch)])
    faces_a = np.array(mesh.patch_areas(patch))
    if np.sum(q * faces_a) < 0:
        q = -q  # convention: positive into the fluid
    bulk_pos, bulk_t = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (positions >= a) & (positions < b)
        if m.sum() < 5:
            continue
        flux = np.abs(velocity[m, ax]) * volumes[m]
        bulk_pos.append(0.5 * (a + b)); bulk_t.append(np.sum(flux * temperature[m]) / flux.sum())
    nu_rows = nusselt_from_bins(faces_x, q, tw, faces_a, bulk_pos, bulk_t, diameter, k, edges)
    developed = [r for r in nu_rows if lo <= r['position_m'] <= hi and math.isfinite(r['nusselt'])]
    nu_cfd = float(np.mean([r['nusselt'] for r in developed])) if developed else float('nan')
    nu_ref = nusselt(reynolds, prandtl, f_ref)
    wall_power = float(np.sum(q * faces_a))
    result = {'case': str(case), 'time': latest.name, 'axis': axis, 'diameter_m': diameter, 'length_m': float(positions.max() - positions.min()),
              'speed_m_s': speed, 'reynolds': reynolds, 'prandtl': prandtl, 'regime': regime,
              'developed_window_m': [lo, hi], 'pressure_gradient_Pa_m': gradient,
              'friction': {'cfd': f_cfd, 'petukhov': f_ref, 'blasius': blasius, 'deviation_percent': 100 * (f_cfd / f_ref - 1)},
              'nusselt': {'cfd_developed_mean': nu_cfd, 'gnielinski': nu_ref, 'deviation_percent': 100 * (nu_cfd / nu_ref - 1) if nu_ref else None,
                          'local': nu_rows},
              'wall_power_into_fluid_W': wall_power, 'heat_input_W': settings['heat_flux_W_m2'] * settings['heated_area_m2'],
              'stations': [{'position_m': x, 'static_pressure_Pa': p, 'bulk_temperature_K': t, 'mean_speed_m_s': u}
                           for x, p, t, u in zip(station_x, station_p, station_tb, station_u)],
              'limitations': 'Correlations are fits of smooth-duct measurements; entry effects are excluded by the window; the local '
                             'Nusselt number uses the mean of the wall temperature around the bore, so one-sided heating biases it slightly.'}
    text = markdown(result)
    if output:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, allow_nan=True) + '\n')
        output.with_suffix('.md').write_text(text)
    return result, text


def markdown(result):
    f, n = result['friction'], result['nusselt']
    lines = [f"### Smooth-duct benchmark ({result['axis']} axis, D {result['diameter_m']*1e3:.2f} mm, L/D {result['length_m']/result['diameter_m']:.0f})", '',
             f"Re {result['reynolds']:.0f} ({result['regime']}), Pr {result['prandtl']:.2f}, mean speed {result['speed_m_s']:.2f} m/s; developed window "
             f"{result['developed_window_m'][0]*1e3:.0f} to {result['developed_window_m'][1]*1e3:.0f} mm.", '',
             '| quantity | CFD | reference | deviation |', '| --- | ---: | ---: | ---: |',
             f"| Darcy friction factor | {f['cfd']:.4f} | {f['petukhov']:.4f} (Petukhov)" + (f", {f['blasius']:.4f} (Blasius)" if f['blasius'] else '') + f" | {f['deviation_percent']:+.1f} % |",
             f"| Nusselt number, developed | {n['cfd_developed_mean']:.1f} | {n['gnielinski']:.1f} (Gnielinski) | " + (f"{n['deviation_percent']:+.1f} %" if n['deviation_percent'] is not None else 'n/a') + ' |',
             f"| wall power into fluid | {result['wall_power_into_fluid_W']:.1f} W | {result['heat_input_W']:.1f} W applied | |", '',
             '| x mm | p bar | T_bulk K | T_wall K | q_wall MW/m2 | Nu |', '| ---: | ---: | ---: | ---: | ---: | ---: |']
    for row in n['local']:
        s = next((st for st in result['stations'] if abs(st['position_m'] - row['position_m']) < 1e-9), None)
        lines.append(f"| {row['position_m']*1e3:.1f} | {s['static_pressure_Pa']/1e5 if s else float('nan'):.4f} | {row['bulk_temperature_K']:.2f} | "
                     f"{row['wall_temperature_K']:.2f} | {row['wall_flux_W_m2']/1e6:.3f} | {row['nusselt']:.1f} |")
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    parser.add_argument('--time')
    parser.add_argument('--axis', default='x', choices=sorted(AXES))
    parser.add_argument('--diameter', type=float, help='bore diameter in m (default: settings hydraulic diameter)')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result, text = run(args.case, args.time, args.axis, args.diameter, output=args.output)
    print(text)


if __name__ == '__main__':
    main()
