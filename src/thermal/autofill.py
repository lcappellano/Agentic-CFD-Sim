"""Estimate the CFD operating point when the review left flow or outlet pressure blank.

Rules, in the order applied (each one is returned as a plain-language reason):

1. Flow: the smallest flow whose spread-bound heated-face temperature uses at most
   ``autofill_temperature_fraction`` (default 0.75) of the allowed rise above the inlet.
2. Subcooling: if the wall is not the margin below saturation at the preferred outlet pressure
   (the fixed or lowest review pressure, else atmospheric), the flow is raised until it is, as
   long as the passage velocity stays within ``plausible_velocity_m_s``; past that the outlet
   pressure makes up the rest (saturation pressure at wall plus margin, rounded up to 0.5 bar).
   A fixed pressure cannot be raised, so the flow is raised regardless and checked.
3. A review lower bound raises a value. Nothing is ever lowered or clamped to fit a limit.
4. Checks: when the estimate needs more than ``plausible_velocity_m_s``,
   ``plausible_outlet_pressure_Pa`` or ``plausible_pressure_drop_Pa``, exceeds a review upper
   bound or the pump limit, or no point exists at all, the estimate comes back with ``stop``
   reasons and the driver asks the operator instead of running CFD. Values fixed by the review
   or the spec only get warnings.

Everything here is a duct-correlation estimate; the CFD audits remain the check.
"""
import math

from src.thermal.prescreen import DEFAULTS, channel_model, estimate
from src.thermal.saturation import saturation_pressure, saturation_temperature, CRITICAL_K

ATMOSPHERE_PA = 101325.
PRESSURE_STEP_PA = 50000.
FLOW_SEARCH_L_MIN = (1e-5, 1e5)
PLAUSIBILITY_KEYS = ('plausible_velocity_m_s', 'plausible_outlet_pressure_Pa', 'plausible_pressure_drop_Pa')


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def round_significant(value, figures=2, up=True):
    """Round away from the estimate: up for a flow that must meet a limit, down for a threshold."""
    if not value:
        return value
    scale = 10. ** (math.floor(math.log10(abs(value))) - figures + 1)
    steps = math.ceil(value / scale - 1e-9) if up else math.floor(value / scale + 1e-9)
    return float(f'{steps * scale:.{figures}g}')


def smallest(predicate, low, high, iterations=60):
    """Smallest x in [low, high] with predicate(x) true, for a predicate false below a threshold
    and true above it (geometric bisection). None when never true, low when always true."""
    if not predicate(high):
        return None
    if predicate(low):
        return low
    for _ in range(iterations):
        mid = math.sqrt(low * high)
        if predicate(mid):
            high = mid
        else:
            low = mid
    return high


def largest(predicate, low, high, iterations=60):
    """Largest x in [low, high] with predicate(x) true, for a predicate true below a threshold."""
    if not predicate(low):
        return None
    if predicate(high):
        return high
    for _ in range(iterations):
        mid = math.sqrt(low * high)
        if predicate(mid):
            low = mid
        else:
            high = mid
    return low


def hot(row):
    """Spread-bound heated-face temperature, or the wall temperature when no ligament is known."""
    value = row['heated_temperature_K']['spread']
    return row['wall_temperature_K']['spread'] if value is None else value


def celsius(value):
    return f'{value - 273.15:.0f} °C'


def bar(value):
    return f'{value / 1e5:.2f} bar'


def review_bounds(handoff_requirements, rho):
    """Flow bounds in L/min and pressure bounds in Pa from the review; None where blank."""
    req = handoff_requirements or {}
    flow = req.get('mass_flow_bounds_kg_s') or [None, None]
    pressure = req.get('outlet_absolute_pressure_bounds_Pa') or [None, None]
    return ([v / rho * 60000. if positive(v) else None for v in flow],
            [v if positive(v) else None for v in pressure])


def subcooling_pressure(wall, margin):
    """Outlet pressure that keeps ``wall`` the margin below saturation; None above the critical point."""
    return saturation_pressure(wall + margin) if wall + margin < CRITICAL_K else None


def choose_operating_point(geometry, basis, operating, options=None, handoff_requirements=None, fixed=None):
    """Flow (L/min) and outlet pressure (Pa) for CFD; ``fixed`` holds values already chosen.
    A non-empty ``stop`` list in the result means the operator has to decide."""
    options = {**DEFAULTS, **(options or {})}
    fixed = fixed or {}
    fraction = float(options['autofill_temperature_fraction'])
    if not 0 < fraction <= 1:
        raise ValueError('autofill_temperature_fraction must be in (0, 1]')
    plausible = {key: float(options[key]) for key in PLAUSIBILITY_KEYS}
    speed_limit = plausible['plausible_velocity_m_s']
    model = channel_model(geometry, options)
    rho = basis['fluid_properties']['density_kg_m3']
    inlet, limit = operating['inlet_temperature_K'], operating['temperature_limit_K']
    margin, supply = options['wall_subcooling_margin_K'], options['supply_pressure_Pa']
    pump = operating.get('max_pump_pressure_rise_Pa')
    target = inlet + fraction * (limit - inlet)
    flow_bounds, pressure_bounds = review_bounds(handoff_requirements, rho)
    fixed_flow, fixed_pressure = fixed.get('volume_flow_L_min'), fixed.get('outlet_absolute_pressure_Pa')
    preferred = fixed_pressure or pressure_bounds[0] or ATMOSPHERE_PA
    cool_wall = saturation_temperature(preferred) - margin
    low, high = FLOW_SEARCH_L_MIN
    reasons, warnings, stop = [], [], []

    def row_at(flow):
        return estimate(flow, model, basis, operating, options)

    def check(condition, text, estimated=True):
        """A violated limit stops an estimated value; a fixed value only gets a warning."""
        if condition:
            (stop if estimated else warnings).append(text)

    def result(flow, pressure, needed_pressure):
        row = row_at(flow) if flow else None
        rise = None if row is None or pressure is None else row['pressure_drop_Pa'] + pressure - supply
        return {'volume_flow_L_min': flow, 'mass_flow_kg_s': None if flow is None else flow / 60000. * rho,
                'outlet_absolute_pressure_Pa': pressure, 'target_temperature_K': target,
                'preferred_outlet_pressure_Pa': preferred, 'required_outlet_pressure_Pa': needed_pressure,
                'estimate': None if row is None else {k: row[k] for k in ('reynolds', 'regime', 'mean_speed_m_s', 'pressure_drop_Pa',
                                                                          'outlet_temperature_K', 'wall_temperature_K', 'heated_temperature_K')},
                'idealised_pump_rise_Pa': rise, 'within_pump_limit': None if pump is None or rise is None else rise <= pump,
                'plausibility': plausible, 'reasons': reasons, 'warnings': warnings, 'stop': stop,
                'basis': 'duct-correlation estimate (prescreen); the CFD audits remain the check'}

    # 1-3. Flow.
    flow, flow_rule = fixed_flow, 'fixed'
    if flow is not None:
        reasons.append(f'Flow {flow:.4g} L/min is fixed by the spec or the review.')
    else:
        needed = smallest(lambda f: hot(row_at(f)) <= target, low, high)
        if needed is None:
            row = row_at(high)
            conduction = row['conduction_rise_K']
            stop.append(f'No flow meets the target {celsius(target)} (limit {celsius(limit)}): at {high:g} L/min the heated face '
                        f'is still {celsius(hot(row))}'
                        + (f'; conduction through the {model["solid_thickness_m"] * 1000:.2f} mm ligament alone adds {conduction:.0f} K.'
                           if conduction else '.'))
            return result(None, None, None)
        flow, flow_rule = round_significant(needed, 2, up=True), 'the temperature target'
        reasons.append(f'Flow {flow:.4g} L/min: the smallest flow whose estimated heated-face temperature (spread bound) stays within '
                       f'{fraction:.0%} of the allowed rise above the inlet, {celsius(target)} against the {celsius(limit)} limit.')
        cool = smallest(lambda f: row_at(f)['wall_temperature_K']['spread'] <= cool_wall, low, high)
        if cool is not None and cool > needed and row_at(needed)['mean_speed_m_s'] <= speed_limit:
            fast = largest(lambda f: row_at(f)['mean_speed_m_s'] <= speed_limit, low, high)
            if fixed_pressure is not None or (fast is not None and fast >= cool):
                flow, flow_rule = max(flow, round_significant(cool, 2, up=True)), f'subcooling at {bar(preferred)}'
                reasons.append(f'Raised to {flow:.4g} L/min so the spread-bound wall temperature stays {margin:.0f} K below saturation '
                               f'at {bar(preferred)}' + (' (fixed by the spec or the review).' if fixed_pressure is not None else '.'))
            elif fast is not None:
                flow = max(flow, round_significant(fast, 2, up=False))
                reasons.append(f'Raised to {flow:.4g} L/min, the most flow within the plausible {speed_limit:g} m/s (staying at '
                               f'{bar(preferred)} would need {round_significant(cool, 2):.4g} L/min); the outlet pressure makes up the rest.')
        lower, upper = flow_bounds
        if lower is not None and flow < lower:
            flow, flow_rule = lower, "the review's lower flow bound"
            reasons.append(f"Raised to the review's lower flow bound {flow:.4g} L/min.")
        check(upper is not None and flow > upper,
              f"The estimate {flow:.4g} L/min is above the review's upper flow bound {upper:.4g} L/min; at that bound the heated face is "
              f'estimated at {celsius(hot(row_at(upper)))} (spread bound, limit {celsius(limit)}).' if upper is not None else '')
    row = row_at(flow)
    check(row['mean_speed_m_s'] > speed_limit,
          f'Mean passage velocity {row["mean_speed_m_s"]:.1f} m/s ({flow:.4g} L/min, set by {flow_rule}) is above the plausible '
          f'{speed_limit:g} m/s.', estimated=fixed_flow is None)
    # 4. Outlet pressure.
    wall = row['wall_temperature_K']['spread']
    needed_pressure = subcooling_pressure(wall, margin)
    pressure = fixed_pressure
    if pressure is not None:
        reasons.append(f'Outlet pressure {bar(pressure)} absolute is fixed by the spec or the review.')
        sat = saturation_temperature(pressure)
        check(sat - wall < margin - 1e-9, f'At {bar(pressure)} the spread-bound wall temperature {celsius(wall)} is only {sat - wall:.0f} K '
              f'below saturation (margin {margin:.0f} K).', estimated=False)
    elif needed_pressure is None:
        stop.append(f'No outlet pressure keeps the wall subcooled: the spread-bound wall temperature {celsius(wall)} plus the '
                    f'{margin:.0f} K margin is above the critical point.')
    else:
        if needed_pressure <= preferred:
            pressure = preferred
            reasons.append(f'Outlet pressure {bar(pressure)} absolute'
                           + (' (atmospheric return)' if pressure == ATMOSPHERE_PA else ' (the lowest pressure the review allows)')
                           + f': the spread-bound wall temperature {celsius(wall)} stays at least {margin:.0f} K below saturation there.')
        else:
            pressure = math.ceil(needed_pressure / PRESSURE_STEP_PA - 1e-9) * PRESSURE_STEP_PA
            reasons.append(f'Outlet pressure {bar(pressure)} absolute: {bar(needed_pressure)} keeps the spread-bound wall temperature '
                           f'{celsius(wall)} {margin:.0f} K below saturation, rounded up to 0.5 bar.')
        upper = pressure_bounds[1]
        check(upper is not None and pressure > upper,
              f"The estimate needs {bar(pressure)} at the outlet, above the review's upper pressure bound {bar(upper)}." if upper is not None else '')
        check(pressure > plausible['plausible_outlet_pressure_Pa'],
              f'The estimate needs {bar(pressure)} at the outlet, above the plausible {bar(plausible["plausible_outlet_pressure_Pa"])}.')
    drop = row['pressure_drop_Pa']
    check(drop > plausible['plausible_pressure_drop_Pa'],
          f'The passage pressure drop {bar(drop)} at {flow:.4g} L/min is above the plausible {bar(plausible["plausible_pressure_drop_Pa"])}.',
          estimated=fixed_flow is None)
    if pressure is not None and pump is not None:
        rise = drop + pressure - supply
        check(rise > pump, f'The idealised pump rise {bar(rise)} (passage drop plus outlet pressure above a {bar(supply)} supply) exceeds '
              f'the {bar(pump)} pump limit.', estimated=fixed_flow is None or fixed_pressure is None)
    peak_pressure = subcooling_pressure(row['wall_temperature_K']['peak'], margin)
    if pressure is not None and (peak_pressure is None or peak_pressure > pressure * (1 + 1e-9)):
        warnings.append('Without heat spreading in the solid (peak bound, wall '
                        f'{celsius(row["wall_temperature_K"]["peak"])}) the outlet would need '
                        + (f'{bar(peak_pressure)}' if peak_pressure else 'more than the critical pressure')
                        + '; the CFD phase screen decides.')
    return result(flow, pressure, needed_pressure)


def explain(choice):
    """Console/report text: the values, then one line per rule, stop reason and warning."""
    flow, pressure = choice['volume_flow_L_min'], choice['outlet_absolute_pressure_Pa']
    if flow is None or pressure is None:
        head = 'No feasible operating point could be estimated from the correlations; operator input needed.'
    else:
        row = choice['estimate']
        head = (('Estimated operating point (not applied; operator input needed): ' if choice.get('stop') else 'Estimated operating point: ')
                + f"{flow:.4g} L/min ({choice['mass_flow_kg_s']:.3g} kg/s) at {pressure / 1e5:.2f} bar absolute. "
                f"Estimated heated face {celsius(hot(row))} (spread bound), outlet {celsius(row['outlet_temperature_K'])}, "
                f"Δp {row['pressure_drop_Pa'] / 1e5:.3g} bar, {row['mean_speed_m_s']:.2g} m/s, Re {row['reynolds']:.0f} ({row['regime']}).")
    lines = ([head] + ['- ' + reason for reason in choice['reasons']] + ['- STOP: ' + reason for reason in choice.get('stop', [])]
             + ['- WARNING: ' + warning for warning in choice['warnings']])
    return '\n'.join(lines)
