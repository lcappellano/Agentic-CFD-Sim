"""Independent field audit of a solved single-phase CHT case.

Reads mesh and fields with the verification reader, rebuilds balances, phase
and transport screens, and reports each check as pass, fail or not checked.
"""
import argparse
import json
import math
from pathlib import Path
import re

from src.foam.hashing import digest
from src.thermal.saturation import saturation_pressure
from src.verification.independent_reader import Mesh, clean, block

SATURATION_SOURCE = 'https://www.iapws.org/relguide/Supp-sat.html'


def transport_spec(settings):
    """Check the saved declaration independently of the CFD adapter."""
    spec = settings.get('transport_polynomials')
    mode = settings.get('transport_model', 'constant')
    if mode not in ('constant', 'polynomial') or (mode == 'polynomial') != (spec is not None):
        raise ValueError('Transport model and polynomial declaration disagree')
    if spec is not None:
        low, high = spec['Tmin_K'], spec['Tmax_K']
        if any(type(v) not in (float, int) or not math.isfinite(v) for v in (low, high)) or not 0 < low < high:
            raise ValueError('Invalid transport fit temperature interval')
        for key in ('muCoeffs8', 'kappaCoeffs8'):
            values = spec[key]
            if not isinstance(values, list) or len(values) != 8 or any(
                    type(v) not in (float, int) or not math.isfinite(v) for v in values):
                raise ValueError('Expected eight finite ascending Kelvin coefficients: ' + key)
    return spec


def transport_at(settings, temperature):
    """No extrapolation, clamping, or replacement with a reference conductivity."""
    spec = settings.get('transport_polynomials')
    if not math.isfinite(temperature):
        raise ValueError('Nonfinite temperature')
    if spec is None:
        values = settings['mu_Pa_s'], settings['k_W_m_K']
    else:
        if not spec['Tmin_K'] <= temperature <= spec['Tmax_K']:
            raise ValueError('Temperature outside declared transport fit range')
        # Independent direct-power summation; the solver adapter uses Horner.
        values = tuple(math.fsum(c * temperature**i for i, c in enumerate(spec[key]))
                       for key in ('muCoeffs8', 'kappaCoeffs8'))
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError('Nonpositive or nonfinite transport property')
    return values


def transport_screen(settings, groups):
    spec = transport_spec(settings)
    result = {'model': settings.get('transport_model', 'constant'), 'groups': {},
              'declared_temperature_interval_K': [spec['Tmin_K'], spec['Tmax_K']] if spec else None,
              'limitation': 'Declared transport evaluation only; not property accuracy or phase validation.'}
    for name, temperatures in groups.items():
        invalid, viscosity, conductivity = 0, [], []
        for temperature in temperatures:
            try:
                mu, kappa = transport_at(settings, temperature)
                viscosity.append(mu)
                conductivity.append(kappa)
            except (ValueError, OverflowError):
                invalid += 1
        result['groups'][name] = {
            'locations': len(temperatures), 'invalid_or_outside_fit_locations': invalid,
            'temperature_range_K': [min(temperatures), max(temperatures)] if temperatures else None,
            'mu_Pa_s_range': [min(viscosity), max(viscosity)] if viscosity else None,
            'k_W_m_K_range': [min(conductivity), max(conductivity)] if conductivity else None}
    result['status'] = 'pass' if groups and all(v['locations'] and not v['invalid_or_outside_fit_locations']
                                               for v in result['groups'].values()) else 'fail'
    return result


def thermo_declaration_check(settings, text):
    """Bind saved settings to supported native dictionaries, including fixed Cp/rho."""
    spec = transport_spec(settings)
    if spec is None:
        expected_names = {'transport': 'const', 'thermo': 'hConst', 'equationOfState': 'rhoConst'}
        expected_scalars = {'rho': settings['rho_kg_m3'], 'Cp': settings['cp_J_kg_K'],
                            'mu': settings['mu_Pa_s'],
                            'Pr': settings['mu_Pa_s'] * settings['cp_J_kg_K'] / settings['k_W_m_K']}
        matches = {}
        for key, value in expected_scalars.items():
            found = re.search(r'\b' + key + r'\s+([^;{}]+);', text)
            matches[key] = bool(found) and math.isclose(float(found.group(1)), value, rel_tol=1e-12)
    else:
        expected_names = {'transport': 'polynomial', 'thermo': 'hPolynomial', 'equationOfState': 'icoPolynomial'}
        arrays = {'rhoCoeffs': [settings['rho_kg_m3']] + [0.] * 7,
                  'CpCoeffs': [settings['cp_J_kg_K']] + [0.] * 7,
                  'muCoeffs': spec['muCoeffs8'], 'kappaCoeffs': spec['kappaCoeffs8']}
        matches = {}
        for key, values in arrays.items():
            found = re.search(r'\b' + key + r'<8>\s*\(([^()]*)\)\s*;', text)
            observed = list(map(float, found.group(1).split())) if found else []
            matches[key] = len(observed) == 8 and all(math.isclose(a, b, rel_tol=1e-12)
                                                     for a, b in zip(observed, values))
    for key, value in expected_names.items():
        matches[key] = bool(re.search(r'\b' + key + r'\s+' + value + r'\s*;', text))
    return {'status': 'pass' if all(matches.values()) else 'fail', 'matches': matches,
            'scope': 'Serialized dictionary/settings consistency only, not runtime implementation validation.'}


def phase_screen(temperatures, pressures, margin_K=10):
    if len(temperatures) != len(pressures):
        raise ValueError('Pressure/temperature association mismatch')
    violations, outside, min_pressure_margin, worst = 0, 0, None, None
    for index, (temperature, pressure) in enumerate(zip(temperatures, pressures)):
        if not 273.16 <= temperature + margin_K <= 647.096 or not 611.657 <= pressure <= 22064000:
            outside += 1
            continue
        threshold = saturation_pressure(temperature + margin_K)
        difference = pressure - threshold
        violations += difference < 0
        if min_pressure_margin is None or difference < min_pressure_margin:
            min_pressure_margin = difference
            worst = {'local_index': index, 'temperature_K': temperature, 'pressure_absolute_Pa': pressure,
                     'required_saturation_pressure_Pa': threshold}
    return {'required_subcooling_margin_K': margin_K, 'paired_locations': len(temperatures),
            'violations': violations, 'outside_correlation_domain': outside,
            'nonpositive_absolute_pressure_locations':sum(p<=0 for p in pressures),
            'minimum_pressure_above_required_saturation_Pa': min_pressure_margin, 'worst_location': worst,
            'status': 'pass' if temperatures and not violations and not outside else 'fail',
            'source': SATURATION_SOURCE,
            'limitation': 'Local equilibrium/subcooling screening only, not onset-of-boiling or CHF validation.'}


def audit(case, settings_path, geometry_path, criteria_path):
    case = Path(case).resolve()
    settings = json.loads(settings_path.read_text())
    transport_spec(settings)
    geometry = json.loads(geometry_path.read_text())
    criteria = json.loads(criteria_path.read_text())
    phase_margin_K = criteria['local_liquid_saturation_margin_K']
    hashes = {str(p): digest(p) for p in (settings_path, geometry_path, criteria_path, Path(__file__))}
    for name in ('manifest.json','settings.json','system/controlDict','system/fluid/fvSchemes',
                 'system/solid/fvSchemes','system/fluid/fvSolution','system/solid/fvSolution',
                 'constant/fluid/thermophysicalProperties','constant/solid/thermophysicalProperties',
                 'constant/fluid/turbulenceProperties','log.solver','log.checkMesh.fluid','log.checkMesh.solid'):
        path = case / name
        if path.is_file():
            hashes[str(path)] = digest(path)
    times = [p for p in case.iterdir() if p.is_dir() and re.fullmatch(r'\d+(?:\.\d+)?', p.name)
             and (p / 'fluid/phi').is_file() and (p / 'solid/T').is_file()]
    latest = max(times, key=lambda p: float(p.name))
    fluid, solid = [Mesh(case / 'constant' / region / 'polyMesh', hashes) for region in ('fluid', 'solid')]
    Tdim, pdim, mdim = [0, 0, 0, 1, 0, 0, 0], [1, -1, -2, 0, 0, 0, 0], [1, 0, -1, 0, 0, 0, 0]
    cp, rho, inlet_T = settings['cp_J_kg_K'], settings['rho_kg_m3'], settings['inlet_temperature_K']
    out = {'scope': 'independent field audit', 'case': str(case), 'time': latest.name, 'ports': {}, 'checks': []}
    def check(name, ok, evidence):
        out['checks'].append({'check': name, 'status': 'pass' if ok else 'fail', 'evidence': evidence})
    declaration = thermo_declaration_check(settings, clean(case / 'constant/fluid/thermophysicalProperties'))
    check('constant_cp_rho_and_transport_dictionary', declaration['status'] == 'pass', declaration)
    transport_temperatures = {}
    for port in ('inlet', 'outlet'):
        patch = fluid.patches[port]
        area = sum(patch['areas'])
        phi = fluid.read(latest / 'fluid/phi', port, mdim)
        temperatures = fluid.read(latest / 'fluid/T', port, Tdim)
        transport_temperatures[port] = temperatures
        pressures = fluid.read(latest / 'fluid/p', port, pdim)
        velocities = fluid.read(latest / 'fluid/U', port, [0, 1, -1, 0, 0, 0, 0])
        speed2 = [sum(x*x for x in v) for v in velocities]
        mass = sum(phi)
        info = {'area_m2': area, 'signed_outward_mass_kg_s': mass,
                'mass_weighted_temperature_K': sum(f*t for f,t in zip(phi,temperatures))/mass,
                'area_average_static_pressure_Pa': sum(a*p for a,p in zip(patch['areas'],pressures))/area,
                'mass_weighted_total_pressure_Pa': sum(f*(p + .5*rho*v2) for f,p,v2 in zip(phi,pressures,speed2))/mass,
                'sensible_outward_energy_W': sum(f*cp*(t-inlet_T) for f,t in zip(phi,temperatures)),
                'kinetic_outward_energy_W': sum(.5*f*v2 for f,v2 in zip(phi,speed2)),
                'reverse_flow_mass_fraction': sum(abs(f) for f in phi if (f>0 if port=='inlet' else f<0))/sum(map(abs,phi))}
        if (latest / 'fluid/gradT').is_file():
            gradients = fluid.read(latest / 'fluid/gradT', port, [0,-1,0,1,0,0,0])
            alphat = fluid.read(latest / 'fluid/alphat', port, [1,-1,-1,0,0,0,0])
            try:
                conductivity = [transport_at(settings, t)[1] for t in temperatures]
                info['conductivity_range_W_m_K'] = [min(conductivity), max(conductivity)]
                info['diffusive_power_into_fluid_W'] = sum((kappa+cp*at)*sum(g*v for g,v in zip(gradient,sf))
                    for gradient,sf,at,kappa in zip(gradients,patch['vectors'],alphat,conductivity))
            except (ValueError, OverflowError) as error:
                info['diffusive_power_into_fluid_W'] = None
                info['diffusion_error'] = str(error)
            info['diffusion_note'] = 'Boundary saved gradT normal component; discretization needs explicit review.'
        else:
            info['diffusive_power_into_fluid_W'] = None
        out['ports'][port] = info
        expected_area = geometry['boundary_map'][port]['area_m2']
        check(port + ':area', abs(area/expected_area-1) <= .01, {'mesh_m2':area,'CAD_m2':expected_area})
        area_vector = [sum(v[j] for v in patch['vectors']) for j in range(3)]
        normal = geometry['port_outward_normals'][port]
        check(port + ':outward_orientation', sum(a*b for a,b in zip(area_vector,normal)) > .99*area,
              {'mesh_area_vector_m2':area_vector,'CAD_normal':normal})
    inlet, outlet = out['ports']['inlet'], out['ports']['outlet']
    out['mass_imbalance_fraction'] = abs(inlet['signed_outward_mass_kg_s']+outlet['signed_outward_mass_kg_s'])/abs(inlet['signed_outward_mass_kg_s'])
    out['static_pressure_drop_Pa'] = inlet['area_average_static_pressure_Pa']-outlet['area_average_static_pressure_Pa']
    out['total_pressure_loss_Pa'] = inlet['mass_weighted_total_pressure_Pa']-outlet['mass_weighted_total_pressure_Pa']
    out['volume_flow_L_min'] = -inlet['signed_outward_mass_kg_s']/rho*60000
    out['mechanical_energy_omission_scale'] = {
        'component_total_pressure_loss_times_volume_flow_W':out['total_pressure_loss_Pa']*(-inlet['signed_outward_mass_kg_s']/rho),
        'limitation':'cpT liquid enthalpy omits pressure-dependent enthalpy and complete viscous-heating fidelity. '
                     'Numerical model energy closure is not physical energy validation.'}
    check('mass_conservation', out['mass_imbalance_fraction'] <= criteria['mass_balance_relative'], out['mass_imbalance_fraction'])
    check('specified_mass_flow', abs(-inlet['signed_outward_mass_kg_s']/settings['mass_flow_kg_s']-1)<=criteria['mass_balance_relative'],
          {'actual_kg_s':-inlet['signed_outward_mass_kg_s'],'settings_kg_s':settings['mass_flow_kg_s']})
    hot = solid.read(latest / 'solid/T', 'heated', Tdim)
    hot_patch = solid.patches['heated']
    hot_index = max(range(len(hot)), key=hot.__getitem__)
    area = sum(hot_patch['areas'])
    out['heated'] = {'maximum_K':hot[hot_index], 'face_centroid_m':hot_patch['centres'][hot_index],
                     'global_face_index':hot_patch['indices'][hot_index], 'area_m2':area,
                     'prescribed_heat_W':area*settings['heat_flux_W_m2']}
    initial_temperature = case / '0/solid/T'
    hashes[str(initial_temperature)] = digest(initial_temperature)
    heating_bc = block(block(clean(initial_temperature), 'boundaryField'), 'heated')
    imposed_flux = re.search(r'\bq\s+uniform\s+([^;]+);', heating_bc)
    check('heat_flux_boundary_matches_settings', imposed_flux is not None
          and math.isclose(float(imposed_flux.group(1)), settings['heat_flux_W_m2'], rel_tol=1e-12),
          {'boundary_q_W_m2': float(imposed_flux.group(1)) if imposed_flux else None,
           'settings_q_W_m2':settings['heat_flux_W_m2']})
    check('heated_area', abs(area/geometry['heated_area_m2']-1)<=.001,
          {'mesh_m2':area,'CAD_m2':geometry['heated_area_m2']})
    wet = fluid.read(latest / 'fluid/T','fluid_to_solid',Tdim)
    wetp = fluid.read(latest / 'fluid/p','fluid_to_solid',pdim)
    out['wetted_maximum_K'] = max(wet)
    check('heated_temperature_limit', max(hot)<settings['temperature_limit_K'],
          {'maximum_K':max(hot),'limit_K':settings['temperature_limit_K']})
    if settings.get('max_pump_pressure_rise_Pa') is not None:
        check('component_total_pressure_budget', 0 <= out['total_pressure_loss_Pa'] <= settings['max_pump_pressure_rise_Pa'],
              {'component_total_pressure_loss_Pa':out['total_pressure_loss_Pa'],
               'pump_differential_ceiling_Pa':settings['max_pump_pressure_rise_Pa'],
               'limitation':'Additional loop/elevation losses not included.'})
    else:
        out['checks'].append({'check':'component_total_pressure_budget','status':'not checked','evidence':'No max_pump_pressure_rise_Pa in settings.'})
    out['phase_wetted'] = phase_screen(wet,wetp,phase_margin_K)
    out['phase_wetted_zero_margin'] = phase_screen(wet,wetp,0)
    for screen in ('phase_wetted','phase_wetted_zero_margin'):
        if out[screen]['worst_location']:
            index = out[screen]['worst_location']['local_index']
            out[screen]['worst_location']['face_centroid_m'] = fluid.patches['fluid_to_solid']['centres'][index]
    bulk_T = fluid.read(latest/'fluid/T', expected_dimensions=Tdim)
    bulk_p = fluid.read(latest/'fluid/p', expected_dimensions=pdim)
    transport_temperatures.update(bulk=bulk_T, wetted=wet)
    out['transport_declared_range'] = transport_screen(settings, transport_temperatures)
    check('transport_declared_range', out['transport_declared_range']['status'] == 'pass',
          out['transport_declared_range'])
    out['phase_bulk'] = phase_screen(bulk_T,bulk_p,phase_margin_K)
    out['phase_bulk_zero_margin'] = phase_screen(bulk_T,bulk_p,0)
    pmin_index = min(range(len(bulk_p)), key=bulk_p.__getitem__)
    out['minimum_bulk_absolute_pressure'] = {'pressure_Pa':bulk_p[pmin_index],
                                            'temperature_K':bulk_T[pmin_index],
                                            **fluid.cell_location(pmin_index)}
    check('positive_absolute_pressure', min(bulk_p+wetp)>0,
          {'bulk_minimum_Pa':min(bulk_p),'wetted_minimum_Pa':min(wetp)})
    for name in ('phase_wetted','phase_bulk'):
        check(name, out[name]['status']=='pass', out[name])
    powers = {}
    for mesh,region,names in ((solid,'solid',('heated','outerWalls','solid_to_fluid')),
                              (fluid,'fluid',('fluid_to_solid',))):
        path = latest / region / 'wallHeatFlux'
        if path.is_file():
            for name in names:
                flux = mesh.read(path,name,[1,0,-3,0,0,0,0])
                powers[region+':'+name] = sum(a*q for a,q in zip(mesh.patches[name]['areas'],flux))
    out['wall_power_into_region_W'] = powers
    Q = out['heated']['prescribed_heat_W']
    scale = out['mechanical_energy_omission_scale']
    scale['fraction_of_applied_heat'] = scale['component_total_pressure_loss_times_volume_flow_W']/Q
    scale['equivalent_bulk_temperature_K'] = scale['component_total_pressure_loss_times_volume_flow_W']/(-inlet['signed_outward_mass_kg_s']*cp)
    if 'solid:heated' in powers:
        check('prescribed_heat_applied', abs(powers['solid:heated']/Q-1)<=criteria['heat_input_relative'], powers['solid:heated'])
    else:
        out['checks'].append({'check':'prescribed_heat_applied','status':'not checked','evidence':'Saved heated wallHeatFlux unavailable.'})
    if all(k in powers for k in ('solid:solid_to_fluid','fluid:fluid_to_solid')):
        fraction = abs(powers['solid:solid_to_fluid']+powers['fluid:fluid_to_solid'])/Q
        check('paired_interface_heat', fraction<=criteria['interface_power_relative'], fraction)
    else:
        out['checks'].append({'check':'paired_interface_heat','status':'not checked','evidence':'Saved paired interface wallHeatFlux unavailable.'})
    advected = sum(p['sensible_outward_energy_W']+p['kinetic_outward_energy_W'] for p in out['ports'].values())
    out['advected_energy_W'] = advected
    diffusion = [p['diffusive_power_into_fluid_W'] for p in out['ports'].values()]
    if all(v is not None for v in diffusion):
        imbalance = abs(advected-Q-sum(diffusion))/Q
        out['energy_imbalance_fraction_using_saved_gradT'] = imbalance
        check('modeled_energy_using_saved_gradT', imbalance<=criteria['energy_balance_relative'], imbalance)
    else:
        out['checks'].append({'check':'modeled_energy','status':'not checked','evidence':'Port diffusion unavailable.'})
    try:
        yp = fluid.read(latest/'fluid/yPlus','fluid_to_solid')
        areas = fluid.patches['fluid_to_solid']['areas']
        out['yplus'] = {'min':min(yp),'max':max(yp),
            'area_fraction_below30':sum(a for a,y in zip(areas,yp) if y<30)/sum(areas),
            'area_fraction_above300':sum(a for a,y in zip(areas,yp) if y>300)/sum(areas)}
    except (OSError, ValueError) as error:
        out['yplus'] = {'status':'not checked','reason':str(error)}
    out['input_sha256'] = hashes
    out['field_checks_pass'] = all(c['status'] == 'pass' for c in out['checks'])
    out['not_checked'] = [c['check'] for c in out['checks'] if c['status'] == 'not checked']
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case',type=Path)
    parser.add_argument('--settings',type=Path,help='defaults to CASE/settings.json')
    parser.add_argument('--geometry',type=Path,help='defaults to CASE/geometry-manifest.json')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--criteria',type=Path,required=True)
    args = parser.parse_args()
    result = audit(args.case,args.settings or args.case/'settings.json',args.geometry or args.case/'geometry-manifest.json',args.criteria)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result,stream,indent=2,allow_nan=False)
        stream.write('\n')
    print(json.dumps({key:result[key] for key in ('case','time','volume_flow_L_min','heated','wetted_maximum_K',
                                               'static_pressure_drop_Pa','total_pressure_loss_Pa','checks')},indent=2))
