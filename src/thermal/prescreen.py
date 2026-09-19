"""Correlation prescreen: flow and outlet-pressure sweep before any CFD.

The passage is reduced to an equivalent duct taken from the geometry manifest:
hydraulic diameter 4V/A_wetted, path length inlet-to-outlet centroid distance,
mean velocity Q·L/V (path length over residence time). Friction uses laminar
64/Re or Petukhov; heat transfer uses Nu = 4.36 or Gnielinski. Two bounds
bracket the wall temperature: ``spread`` uses the mean wetted flux (the solid
spreads the heat over the whole wetted area, usual for copper); ``peak`` uses
the larger of the heated-face flux and the mean wetted flux (no spreading). Conduction through the ligament under the
heated face uses the measured distance from the geometry. The result is a
table for the operator, not a prediction.
"""
import math

from src.thermal.saturation import saturation_pressure, saturation_temperature, CRITICAL_K

DEFAULTS = {'minor_loss_coefficient': 2.5, 'path_length_factor': 1.0, 'wall_subcooling_margin_K': 10.,
            'supply_pressure_Pa': 101325., 'points': 8, 'flow_range_L_min': None, 'flows_L_min': None,
            'outlet_pressures_bar': None, 'flow_path_length_m': None, 'hydraulic_diameter_m': None,
            'solid_thickness_m': None, 'autofill_temperature_fraction': .75,
            'plausible_velocity_m_s': 10., 'plausible_outlet_pressure_Pa': 10e5, 'plausible_pressure_drop_Pa': 5e5}
DEFAULT_FLOW_RANGE = [1., 50.]
DEFAULT_PRESSURES_BAR = [1.01325, 2., 4., 8.]


def friction_factor(reynolds):
    """Darcy friction factor and regime label."""
    if reynolds < 2300:
        return 64. / reynolds, 'laminar'
    factor = (0.79 * math.log(reynolds) - 1.64) ** -2
    return factor, 'transitional' if reynolds < 4000 else 'turbulent'


def nusselt(reynolds, prandtl, factor):
    """Constant-flux laminar value or Gnielinski (3000 < Re < 5e6, 0.5 < Pr < 2000)."""
    if reynolds < 2300:
        return 4.36
    return (factor / 8) * (reynolds - 1000) * prandtl / (1 + 12.7 * math.sqrt(factor / 8) * (prandtl ** (2 / 3) - 1))


def channel_model(geometry, options):
    """Equivalent-duct parameters from a geometry manifest plus explicit overrides."""
    volume = geometry['regions']['fluid']['volume_m3']
    wetted = geometry['boundary_map']['interface']['area_m2']
    inlet, outlet = geometry['boundary_map']['inlet'], geometry['boundary_map']['outlet']
    length = options.get('flow_path_length_m') or math.dist(inlet['centroids_m'][0], outlet['centroids_m'][0]) * options['path_length_factor']
    thickness = options.get('solid_thickness_m')
    if thickness is None:
        thickness = geometry.get('heated_to_passage_distance_m')
    model = {'fluid_volume_m3': volume, 'wetted_area_m2': wetted, 'heated_area_m2': geometry['heated_area_m2'],
             'hydraulic_diameter_m': options.get('hydraulic_diameter_m') or 4 * volume / wetted,
             'flow_path_length_m': length, 'port_area_m2': inlet['area_m2'],
             'solid_thickness_m': thickness, 'minor_loss_coefficient': options['minor_loss_coefficient'],
             'sources': {'hydraulic_diameter': 'override' if options.get('hydraulic_diameter_m') else '4V/A_wetted',
                         'flow_path_length': 'override' if options.get('flow_path_length_m') else 'inlet-outlet centroid distance x path_length_factor',
                         'solid_thickness': 'override' if options.get('solid_thickness_m') else ('geometry heated_to_passage_distance_m' if thickness else 'unknown')}}
    for key in ('fluid_volume_m3', 'wetted_area_m2', 'heated_area_m2', 'hydraulic_diameter_m', 'flow_path_length_m', 'port_area_m2'):
        if not math.isfinite(model[key]) or model[key] <= 0:
            raise ValueError(f'Prescreen needs a positive {key}')
    return model


def estimate(flow_L_min, model, basis, operating, options):
    fluid, solid = basis['fluid_properties'], basis['solid_properties']
    rho, cp, mu, k = fluid['density_kg_m3'], fluid['cp_J_kg_K'], fluid['dynamic_viscosity_Pa_s'], fluid['conductivity_W_m_K']
    flux = operating['heat_flux_W_m2']
    power = flux * model['heated_area_m2']
    inlet_T, limit = operating['inlet_temperature_K'], operating['temperature_limit_K']
    margin = options['wall_subcooling_margin_K']
    volume_rate = flow_L_min / 60000.
    mass = rho * volume_rate
    speed = volume_rate * model['flow_path_length_m'] / model['fluid_volume_m3']
    port_speed = volume_rate / model['port_area_m2']
    diameter = model['hydraulic_diameter_m']
    reynolds = rho * speed * diameter / mu
    prandtl = cp * mu / k
    factor, regime = friction_factor(reynolds)
    nu = nusselt(reynolds, prandtl, factor)
    h = nu * k / diameter
    dp_friction = factor * model['flow_path_length_m'] / diameter * rho * speed ** 2 / 2
    dp_minor = model['minor_loss_coefficient'] * rho * port_speed ** 2 / 2
    outlet_T = inlet_T + power / (mass * cp)
    mean_flux = power / model['wetted_area_m2']
    wall = {'spread': outlet_T + mean_flux / h, 'peak': outlet_T + max(flux, mean_flux) / h}
    conduction = flux * model['solid_thickness_m'] / solid['conductivity_W_m_K'] if model['solid_thickness_m'] else None
    heated = {bound: (value + conduction if conduction is not None else None) for bound, value in wall.items()}
    minimum_pressure = {}
    for bound, value in wall.items():
        minimum_pressure[bound] = saturation_pressure(value + margin) if value + margin <= CRITICAL_K else None
    return {'flow_L_min': flow_L_min, 'mass_flow_kg_s': mass, 'mean_speed_m_s': speed, 'port_speed_m_s': port_speed,
            'reynolds': reynolds, 'prandtl': prandtl, 'regime': regime, 'friction_factor': factor, 'nusselt': nu,
            'heat_transfer_coefficient_W_m2_K': h, 'wall_flux_W_m2': {'spread': mean_flux, 'peak': max(flux, mean_flux)},
            'pressure_drop_Pa': dp_friction + dp_minor,
            'friction_pressure_drop_Pa': dp_friction, 'minor_pressure_drop_Pa': dp_minor,
            'outlet_temperature_K': outlet_T, 'wall_temperature_K': wall, 'heated_temperature_K': heated,
            'conduction_rise_K': conduction, 'minimum_outlet_pressure_Pa': minimum_pressure,
            'heated_within_limit': {bound: (value is not None and value <= limit) for bound, value in heated.items()},
            'correlation_valid': (4000 <= reynolds <= 5e6 and 0.5 <= prandtl <= 2000) or reynolds < 2300}


def flows_for(options, handoff_requirements, rho, centre=None):
    """Sweep flows: spec list or range, else the review range, else a decade around the estimate."""
    if options.get('flows_L_min'):
        return sorted(float(v) for v in options['flows_L_min']), 'spec flows_L_min'
    if options.get('flow_range_L_min'):
        low, high = options['flow_range_L_min']
        source = 'spec flow_range_L_min'
    else:
        bounds = (handoff_requirements or {}).get('mass_flow_bounds_kg_s') or [None, None]
        if all(isinstance(v, (int, float)) and v > 0 for v in bounds) and bounds[0] < bounds[1]:
            low, high = (v / rho * 60000 for v in bounds)
            source = 'handoff mass_flow_bounds_kg_s converted with inlet density'
        elif centre:
            low, high = centre / 10., centre * 10.
            source = 'decade around the autofill estimate'
        else:
            low, high = DEFAULT_FLOW_RANGE
            source = 'default range; set prescreen.flow_range_L_min'
    points = int(options['points'])
    if not 0 < low < high or points < 2:
        raise ValueError('flow_range_L_min must be increasing and positive with at least two points')
    return [low * (high / low) ** (i / (points - 1)) for i in range(points)], source


def pressures_for(options, handoff_requirements, include=None):
    """Sweep pressures: spec list, else four across the review range, else a default list; the
    estimate is added to the non-spec lists so the table shows the chosen column."""
    if options.get('outlet_pressures_bar'):
        return sorted(float(v) * 1e5 for v in options['outlet_pressures_bar']), 'spec outlet_pressures_bar'
    bounds = (handoff_requirements or {}).get('outlet_absolute_pressure_bounds_Pa') or [None, None]
    if all(isinstance(v, (int, float)) and v > 0 for v in bounds) and bounds[0] < bounds[1]:
        low, high = bounds
        values, source = [low * (high / low) ** (i / 3) for i in range(4)], 'handoff outlet_absolute_pressure_bounds_Pa'
    else:
        values, source = [v * 1e5 for v in DEFAULT_PRESSURES_BAR], 'default list; set prescreen.outlet_pressures_bar'
    if include is not None and all(abs(v - include) > 1e-6 * include for v in values):
        values = sorted(values + [include])
    return values, source


def prescreen(geometry, basis, operating, options=None, handoff_requirements=None, fixed=None):
    """Sweep table plus the autofill estimate; ``fixed`` carries flow/pressure already chosen."""
    from src.thermal.autofill import choose_operating_point
    options = {**DEFAULTS, **(options or {})}
    for key in ('inlet_temperature_K', 'temperature_limit_K', 'heat_flux_W_m2'):
        if operating.get(key) is None:
            raise ValueError(f'Prescreen needs operating.{key} (from the handoff or the spec)')
    model = channel_model(geometry, options)
    rho = basis['fluid_properties']['density_kg_m3']
    choice = choose_operating_point(geometry, basis, operating, options, handoff_requirements, fixed)
    flows, flow_source = flows_for(options, handoff_requirements, rho, choice['volume_flow_L_min'])
    pressures, pressure_source = pressures_for(options, handoff_requirements, choice['outlet_absolute_pressure_Pa'])
    rows = [estimate(flow, model, basis, operating, options) for flow in flows]
    margin = options['wall_subcooling_margin_K']
    matrix = []
    for row in rows:
        cells = []
        for pressure in pressures:
            sat = saturation_temperature(pressure)
            cells.append({'outlet_pressure_Pa': pressure,
                          'wall_subcooling_K': {b: sat - row['wall_temperature_K'][b] for b in ('spread', 'peak')},
                          'pass': {b: sat - row['wall_temperature_K'][b] >= margin for b in ('spread', 'peak')},
                          'idealised_pump_rise_Pa': row['pressure_drop_Pa'] + pressure - options['supply_pressure_Pa']})
        matrix.append(cells)
    warnings = []
    if model['solid_thickness_m'] is None:
        warnings.append('No ligament thickness: heated-face temperature omits conduction through the solid.')
    if any(not r['correlation_valid'] for r in rows):
        warnings.append('Some flows are transitional (2300 < Re < 4000) or outside the Gnielinski range; treat those rows as rough.')
    if 'default range' in flow_source:
        warnings.append('No flow estimate to centre the sweep on; set prescreen.flow_range_L_min to match the hardware.')
    return {'status': 'correlation_estimate', 'model': model, 'options': options, 'flow_source': flow_source,
            'pressure_source': pressure_source, 'pressures_Pa': pressures, 'rows': rows, 'matrix': matrix,
            'autofill': choice, 'warnings': warnings,
            'assumptions': ['Equivalent duct: D_h = 4V/A_wetted, L = inlet-outlet centroid distance, u = Q·L/V.',
                            'Petukhov friction plus a lumped minor-loss coefficient on the port dynamic pressure.',
                            'Gnielinski heat transfer at the outlet bulk temperature; fully developed, smooth walls.',
                            'spread: mean wetted flux; peak: max(heated-face flux, mean wetted flux) at the wall.',
                            'Constant properties at the inlet state; no boiling, CHF or manifold maldistribution.']}


def celsius(value):
    return '-' if value is None or not math.isfinite(value) else f'{value - 273.15:.0f}'


def markdown(result, operating):
    limit_C = operating['temperature_limit_K'] - 273.15
    model = result['model']
    lines = ['### Correlation prescreen (not CFD)', '',
             f"Equivalent duct: D_h {model['hydraulic_diameter_m']*1000:.2f} mm, path {model['flow_path_length_m']*1000:.0f} mm, "
             f"wetted {model['wetted_area_m2']*1e4:.1f} cm², heated {model['heated_area_m2']*1e4:.1f} cm², "
             f"ligament {'-' if not model['solid_thickness_m'] else f'{model['solid_thickness_m']*1000:.2f} mm'}, "
             f"K_minor {model['minor_loss_coefficient']}. Limit {limit_C:.0f} °C; wall margin {result['options']['wall_subcooling_margin_K']:.0f} K.", '',
             '| flow L/min | u m/s | Re | regime | Δp bar | T_out °C | T_wall °C spread/peak | T_heated °C spread/peak | p_out,min bar spread/peak |',
             '| ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |']
    for row in result['rows']:
        pmin = row['minimum_outlet_pressure_Pa']
        fmt = lambda v: '>crit' if v is None else f'{v/1e5:.2f}'
        lines.append(f"| {row['flow_L_min']:.4g} | {row['mean_speed_m_s']:.3g} | {row['reynolds']:.0f} | {row['regime']} | "
                     f"{row['pressure_drop_Pa']/1e5:.3g} | {celsius(row['outlet_temperature_K'])} | "
                     f"{celsius(row['wall_temperature_K']['spread'])} / {celsius(row['wall_temperature_K']['peak'])} | "
                     f"{celsius(row['heated_temperature_K']['spread'])} / {celsius(row['heated_temperature_K']['peak'])} | "
                     f"{fmt(pmin['spread'])} / {fmt(pmin['peak'])} |")
    header = '| flow L/min | ' + ' | '.join(f'{p/1e5:.2f} bar' for p in result['pressures_Pa']) + ' |'
    lines += ['', 'Wall subcooling at each outlet pressure, spread bound (ok ≥ margin) and idealised pump rise:', '',
              header, '| ---: |' + ' ---: |' * len(result['pressures_Pa'])]
    for row, cells in zip(result['rows'], result['matrix']):
        cell_text = []
        for cell in cells:
            mark = 'ok' if cell['pass']['spread'] else 'NO'
            cell_text.append(f"{mark} {cell['wall_subcooling_K']['spread']:.0f} K, pump {cell['idealised_pump_rise_Pa']/1e5:.2f} bar")
        lines.append(f"| {row['flow_L_min']:.4g} | " + ' | '.join(cell_text) + ' |')
    from src.thermal.autofill import explain
    lines += ['', explain(result['autofill'])]
    for warning in result['warnings']:
        lines.append('- ' + warning)
    return '\n'.join(lines) + '\n'
