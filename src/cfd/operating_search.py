"""Deterministic fixed-geometry flow bracketing, separate from expensive execution.

Only independently accepted single-phase points may bracket an operating limit.
A failed numerical/physical model is never classified as a thermal failure.
The manager runs each returned point through the same reusable case pipeline.
"""
from dataclasses import dataclass
import math

@dataclass(frozen=True, kw_only=True)
class Point:
    """Accepted point using the reviewed whole-system pump pressure budget.

    pump_pressure_rise_Pa is NOT the component static or total pressure drop.
    For equal-elevation atmospheric stationary reservoirs and no external losses,
    it is mass-flow-weighted inlet total pressure minus suction pressure. Include
    reviewed pipe/fitting/elevation terms for other systems. Use keyword arguments
    so legacy positional component-drop values cannot migrate silently.
    """
    flow_L_min: float
    pump_pressure_rise_Pa: float
    heated_temperature_K: float
    numerically_verified: bool
    physically_applicable: bool


def next_flow(points,flow_bounds,temperature_limit_K,pump_limit_Pa,pressure_tolerance=.1):
    """Return a flow proposal or explicit stop, never an unearned minimum claim.

    Assumes on a reviewed branch that cooling improves and pump pressure grows
    with flow. Monotonicity must be checked against every newly accepted result.
    """
    lo,hi=flow_bounds
    if not (0<lo<hi and 0<pressure_tolerance<1):raise ValueError('Invalid search bounds')
    if not points:return {'status':'run_baseline','flow_L_min':hi}
    if any(not p.numerically_verified or not p.physically_applicable for p in points):
        return {'status':'blocked_model_or_numerics','flow_L_min':None}
    ordered=sorted(points,key=lambda p:p.flow_L_min)
    for a,b in zip(ordered,ordered[1:]):
        if b.pump_pressure_rise_Pa<a.pump_pressure_rise_Pa or b.heated_temperature_K>a.heated_temperature_K+1:
            return {'status':'review_nonmonotonic_response','flow_L_min':None}
    passing=[p for p in ordered if p.heated_temperature_K<=temperature_limit_K and p.pump_pressure_rise_Pa<=pump_limit_Pa]
    if not passing:
        return {'status':'no_feasible_point_yet','flow_L_min':None,'note':'A failing sampled point does not prove infeasibility over all bounds.'}
    upper=min(passing,key=lambda p:p.flow_L_min)
    failing=[p for p in ordered if p.flow_L_min<upper.flow_L_min and p.heated_temperature_K>temperature_limit_K]
    if failing:
        lower=max(failing,key=lambda p:p.flow_L_min)
        if lower.pump_pressure_rise_Pa>0 and upper.pump_pressure_rise_Pa/lower.pump_pressure_rise_Pa-1<=pressure_tolerance:
            return {'status':'bracketed','flow_L_min':None,'passing':upper.__dict__,'failing':lower.__dict__,'note':'Pump-pressure bracket resolution excludes model/mesh and external-system uncertainty.'}
        return {'status':'bisect_flow','flow_L_min':math.sqrt(lower.flow_L_min*upper.flow_L_min)}
    if upper.flow_L_min==lo:return {'status':'lower_bound_passes','flow_L_min':None,'passing':upper.__dict__}
    return {'status':'seek_lower_bracket','flow_L_min':max(lo,upper.flow_L_min*.7)}
