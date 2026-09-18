"""Fit liquid-water viscosity and conductivity polynomials for OpenFOAM.

Uses CoolProp HEOS (IAPWS-95 water), pinned in requirements-engineering.txt.
The fitted law depends on temperature at a declared reference pressure; the
fit range is enforced downstream by the field audits (no clamping in the solver).
"""
import argparse
import json
from pathlib import Path

from src.foam.hashing import digest


def fit_transport(basis, low, high, pressure, order=7):
    import CoolProp
    from CoolProp.CoolProp import PropsSI
    import numpy as np
    from numpy.polynomial import Polynomial

    if not 273.16 <= low < high < PropsSI('T', 'P', pressure, 'Q', 0, 'Water'):
        raise ValueError('Fit range must be entirely liquid at the reference pressure')
    sample = np.linspace(low, high, 241)
    validation = np.linspace(low, high, 2001)
    transport = {'Tmin_K': low, 'Tmax_K': high, 'reference_pressure_Pa': pressure,
                 'backend': 'CoolProp HEOS::Water (IAPWS-95)', 'CoolProp_version': CoolProp.__version__,
                 'coefficient_order': 'ascending powers of temperature in kelvin', 'fit_errors': {}}
    for prop, key in [('V', 'muCoeffs8'), ('L', 'kappaCoeffs8')]:
        values = np.array([PropsSI(prop, 'T', t, 'P', pressure, 'Water') for t in sample])
        coefficients = Polynomial.fit(sample, values, order, w=1 / values).convert().coef
        expected = np.array([PropsSI(prop, 'T', t, 'P', pressure, 'Water') for t in validation])
        calculated = Polynomial(coefficients)(validation)
        error = float(np.max(np.abs(calculated / expected - 1)))
        if np.any(calculated <= 0) or not np.all(np.isfinite(calculated)) or error > .01:
            raise ValueError(f'{key}: invalid or inaccurate polynomial, max relative error={error}')
        transport[key] = coefficients.tolist()
        transport['fit_errors'][key] = {'max_relative': error, 'validation_points': len(validation)}
    out = dict(basis)
    out['transport_model'] = 'polynomial'
    out['transport_polynomials'] = transport
    out['limitations'] = list(basis.get('limitations', [])) + [
        'Transport fitted at one reference pressure; cp and density remain constant.',
        'Liquid coefficients are invalid in vapor/cavitating regions.']
    out['sources'] = list(basis.get('sources', [])) + ['https://coolprop.org/fluid_properties/IF97.html']
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--basis', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--temperature-range', type=float, nargs=2, required=True)
    parser.add_argument('--reference-pressure-Pa', type=float, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Use a fresh versioned output')
    out = fit_transport(json.loads(args.basis.read_text()), *args.temperature_range, args.reference_pressure_Pa)
    out['fit_input_sha256'] = {str(p): digest(p) for p in (args.basis, Path(__file__))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2, allow_nan=False) + '\n')
    print(json.dumps(out['transport_polynomials'], indent=2))


if __name__ == '__main__':
    main()
