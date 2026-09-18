"""Sample transport-fit pressure sensitivity at stable liquid states only."""
import argparse
import json
from pathlib import Path

from src.foam.hashing import digest


def evaluate(basis, pressure_bounds, samples=31):
    import CoolProp
    from CoolProp.CoolProp import PropsSI

    spec = basis['transport_polynomials']
    fluid = basis['fluid_properties']
    low, high = pressure_bounds
    if not 0 < low <= high or samples < 2:
        raise ValueError('Require positive ordered pressures and at least two samples')
    metrics = {}
    skipped = valid = 0
    for i in range(samples):
        pressure = low + (high - low) * i / (samples - 1)
        saturation = PropsSI('T', 'P', pressure, 'Q', 0, 'Water')
        for j in range(samples):
            temperature = spec['Tmin_K'] + (spec['Tmax_K'] - spec['Tmin_K']) * j / (samples - 1)
            if temperature >= saturation:
                skipped += 1
                continue
            valid += 1
            for output, prop, coefficients in [
                    ('viscosity', 'V', spec['muCoeffs8']),
                    ('conductivity', 'L', spec['kappaCoeffs8']),
                    ('density_constant', 'D', [fluid['density_kg_m3']]),
                    ('cp_constant', 'C', [fluid['cp_J_kg_K']])]:
                fitted = 0.
                for coefficient in reversed(coefficients):
                    fitted = fitted * temperature + coefficient
                actual = PropsSI(prop, 'T', temperature, 'P', pressure, 'Water')
                error = abs(fitted / actual - 1)
                if output not in metrics or error > metrics[output]['max_sampled_relative_error']:
                    metrics[output] = dict(max_sampled_relative_error=error, temperature_K=temperature,
                                           pressure_Pa=pressure, model_value=fitted, reference_value=actual)
    return dict(status='sampled_property_comparison', CoolProp_version=CoolProp.__version__,
                pressure_bounds_Pa=[low, high], temperature_bounds_K=[spec['Tmin_K'], spec['Tmax_K']],
                samples_per_axis=samples, stable_liquid_samples=valid,
                excluded_nonliquid_samples=skipped, comparisons=metrics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--basis', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pressure-range-Pa', type=float, nargs=2, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Use a fresh versioned output')
    result = evaluate(json.loads(args.basis.read_text()), args.pressure_range_Pa)
    result['input_sha256'] = {str(p): digest(p) for p in [args.basis, Path(__file__)]}
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps(result['comparisons'], indent=2))


if __name__ == '__main__':
    main()
