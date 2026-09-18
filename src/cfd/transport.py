"""Native OpenCFD v2412 liquid transport dictionaries with constant rho and Cp.

Polynomial coefficients are ascending powers of absolute temperature in kelvin.
Coefficients are fitted by ``src.thermal.fit_water_transport``, never here.
"""
import math

from src.foam.dictionary import coefficient_array


def polynomial(coefficients, temperature_K):
    """Horner evaluation of exactly the polynomial supplied to OpenFOAM."""
    result = 0.0
    for coefficient in reversed(coefficients):
        result = result * temperature_K + coefficient
    return result


def validate_polynomials(spec, inlet_temperature_K=None):
    low, high = spec['Tmin_K'], spec['Tmax_K']
    if not all(type(v) in (int, float) and math.isfinite(v) for v in (low, high)) or not 0 < low < high:
        raise ValueError('Transport requires positive finite Tmin_K < Tmax_K')
    if inlet_temperature_K is not None and not low <= inlet_temperature_K <= high:
        raise ValueError('Inlet temperature outside transport fit range')
    for key in ('muCoeffs8', 'kappaCoeffs8'):
        coefficients = spec[key]
        if not isinstance(coefficients, list) or len(coefficients) != 8 or \
                any(type(v) not in (int, float) or not math.isfinite(v) for v in coefficients):
            raise ValueError(key + ' must contain eight finite ascending-power coefficients')
        for i in range(1001):
            value = polynomial(coefficients, low + (high - low) * i / 1000)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(key + ' is not positive throughout the sampled fit interval')
    return spec


def fluid_dictionary(basis, inlet_temperature_K):
    fluid = basis['fluid_properties']
    rho, cp, mu, kappa = (fluid[k] for k in ('density_kg_m3', 'cp_J_kg_K', 'dynamic_viscosity_Pa_s', 'conductivity_W_m_K'))
    if any(not math.isfinite(v) or v <= 0 for v in (rho, cp, mu, kappa)):
        raise ValueError('Fluid reference properties must be positive and finite')
    weight = fluid.get('molecular_weight', 18.015)
    spec = basis.get('transport_polynomials')
    if spec is None:
        return (f'thermoType {{ type heRhoThermo; mixture pureMixture; transport const; thermo hConst; '
                f'equationOfState rhoConst; specie specie; energy sensibleEnthalpy; }}\n'
                f'mixture {{ specie {{ molWeight {weight}; }} equationOfState {{ rho {rho}; }} '
                f'thermodynamics {{ Cp {cp}; Hf 0; }} transport {{ mu {mu}; Pr {mu * cp / kappa}; }} }}')
    validate_polynomials(spec, inlet_temperature_K)
    return (f'thermoType {{ type heRhoThermo; mixture pureMixture; transport polynomial; thermo hPolynomial; '
            f'equationOfState icoPolynomial; specie specie; energy sensibleEnthalpy; }}\n'
            f'mixture\n{{\n    specie {{ molWeight {weight}; }}\n'
            f'    equationOfState {{ rhoCoeffs<8> {coefficient_array([rho] + [0.0] * 7)}; }}\n'
            f'    thermodynamics {{ Hf 0; Sf 0; CpCoeffs<8> {coefficient_array([cp] + [0.0] * 7)}; }}\n'
            f'    transport {{ muCoeffs<8> {coefficient_array(spec["muCoeffs8"])}; '
            f'kappaCoeffs<8> {coefficient_array(spec["kappaCoeffs8"])}; }}\n}}')


def solid_dictionary(basis):
    solid = basis['solid_properties']
    return (f'thermoType {{ type heSolidThermo; mixture pureMixture; transport constIso; thermo hConst; '
            f'equationOfState rhoConst; specie specie; energy sensibleEnthalpy; }}\n'
            f'mixture {{ specie {{ molWeight {solid.get("molecular_weight", 63.546)}; }} '
            f'equationOfState {{ rho {solid["density_kg_m3"]}; }} thermodynamics {{ Cp {solid["cp_J_kg_K"]}; Hf 0; }} '
            f'transport {{ kappa {solid["conductivity_W_m_K"]}; }} }}')


def conductivity_values(settings, temperatures):
    """Declared k(T) at each temperature; rejects extrapolation rather than clamping."""
    spec = settings.get('transport_polynomials')
    if spec is None:
        return [settings['k_W_m_K']] * len(temperatures)
    low, high = spec['Tmin_K'], spec['Tmax_K']
    values = []
    for temperature in temperatures:
        if not math.isfinite(temperature) or not low <= temperature <= high:
            raise ValueError('Saved temperature outside transport fit range')
        value = polynomial(spec['kappaCoeffs8'], temperature)
        if not math.isfinite(value) or value <= 0:
            raise ValueError('Invalid saved thermal conductivity')
        values.append(value)
    return values
