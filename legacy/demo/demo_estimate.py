"""Screen the approved straight-bore demo; correlations are not CFD validation.

Run through tools/workbench.py job. Standard library only.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

WATER = dict(density_kg_m3=997.047013, cp_J_kg_K=4181.44618,
             dynamic_viscosity_Pa_s=0.00085372003, conductivity_W_m_K=0.609485)
COPPER = dict(density_kg_m3=8920, cp_J_kg_K=394, conductivity_W_m_K=394)


def saturation_pressure(T):
    """IAPWS SR1-86(1992), Pa, triple point to critical point."""
    if not 273.16 <= T <= 647.096:
        raise ValueError('Saturation temperature outside triple-to-critical range')
    tau = 1 - T / 647.096
    coeff = (-7.85951783, 1.84408259, -11.7866497, 22.6807411,
             -15.9618719, 1.80122502)
    powers = (1, 1.5, 3, 3.5, 4, 7.5)
    return 22.064e6 * math.exp(647.096 / T * sum(a*tau**b for a,b in zip(coeff,powers)))


def saturation_temperature(p):
    if not saturation_pressure(273.16) <= p <= 22.064e6:
        raise ValueError('Pressure outside saturation range')
    lo, hi = 273.16, 647.096
    for _ in range(70):
        mid = (lo + hi) / 2
        if saturation_pressure(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def estimate(project, model):
    faces = {f['id']: f for f in model['faces'] + model['virtual_faces']}
    inlet = faces[project['inlet_faces'][0]]
    outlet = faces[project['outlet_faces'][0]]
    D = 2 * inlet['radius_mm'] / 1000
    L = math.dist(inlet['centroid_mm'], outlet['centroid_mm']) / 1000
    if model['units'] != 'mm' or abs(D-.008)>1e-8 or abs(L-.06)>1e-8:
        raise ValueError('Only the verified 8 mm x 60 mm demo is supported')
    Ahot = sum(faces[f]['area_mm2'] for f in project['heated_faces']) * 1e-6
    Q = project['heat_flux_W_m2'] * Ahot
    Awet = math.pi*D*L
    rho, cp, mu, k = WATER.values()
    Pr = cp*mu/k
    rows = []
    for m in sorted(set([project['mass_flow_bounds_kg_s'][0], 1.0, project['mass_flow_bounds_kg_s'][1]])):
        u = m/rho/(math.pi*D**2/4)
        Re = rho*u*D/mu
        f = (0.79*math.log(Re)-1.64)**-2
        Nu = (f/8)*(Re-1000)*Pr/(1+12.7*math.sqrt(f/8)*(Pr**(2/3)-1))
        h = Nu*k/D
        dp = f*L/D*rho*u*u/2
        dT = Q/(m*cp)
        rows.append(dict(mass_flow_kg_s=m, volume_flow_L_s=m/rho*1000,
                         mean_velocity_m_s=u, Reynolds=Re, Prandtl=Pr,
                         Darcy_friction_factor=f, friction_only_pressure_drop_Pa=dp,
                         friction_only_hydraulic_power_W=dp*m/rho,
                         dynamic_pressure_Pa=rho*u*u/2,
                         bulk_temperature_rise_K=dT, Nusselt=Nu,
                         heat_transfer_coefficient_W_m2_K=h,
                         uniform_wetted_flux_wall_temperature_screen_K=project['inlet_temperature_K']+dT+Q/Awet/h,
                         correlation_Re_Pr_in_range=3000<Re<5e6 and .5<Pr<2000))
    return dict(status='analytical_screening_not_CFD', geometry=dict(diameter_m=D,length_m=L,
                heated_area_m2=Ahot,wetted_area_m2=Awet,length_to_diameter=L/D),
                total_applied_heat_W=Q, water_properties=WATER,copper_properties=COPPER,
                cases=rows, outlet_pressure_bounds_Pa=project['outlet_absolute_pressure_bounds_Pa'],
                saturation_temperatures_at_outlet_bounds_K=[saturation_temperature(p) for p in project['outlet_absolute_pressure_bounds_Pa']],
                saturation_pressure_at_300K_Pa=saturation_pressure(300),
                limitations=['Short entry flow, asymmetric heating and local copper spreading are not resolved.',
                'Uniform wetted-wall temperature screen is neither maximum heated-face temperature nor an upper bound.',
                'Pressure drop includes straight-bore fully developed friction only, not entrance or whole-loop losses.',
                'High-flow bound is screening only: pressure-dependent properties and viscous dissipation may matter.'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run',type=Path,required=True)
    args=ap.parse_args()
    project_path=args.run/'project.json'
    model_path=args.run/'requirements_review/model.json'
    result=estimate(json.loads(project_path.read_text()),json.loads(model_path.read_text()))
    result['input_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (project_path,model_path)}
    out=args.run/'thermal/estimates.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
