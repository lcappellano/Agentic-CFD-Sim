"""IAPWS SR1-86(1992) water saturation curve, triple point to critical point.

Source: https://www.iapws.org/relguide/Supp-sat.html
"""
import math

TRIPLE_K, CRITICAL_K, CRITICAL_PA = 273.16, 647.096, 22.064e6
_COEFFICIENTS = (-7.85951783, 1.84408259, -11.7866497, 22.6807411, -15.9618719, 1.80122502)
_POWERS = (1, 1.5, 3, 3.5, 4, 7.5)


def saturation_pressure(temperature_K):
    """Saturation pressure in Pa for a temperature in kelvin."""
    if not TRIPLE_K <= temperature_K <= CRITICAL_K:
        raise ValueError('Saturation temperature outside triple-to-critical range')
    tau = 1 - temperature_K / CRITICAL_K
    series = sum(a * tau ** b for a, b in zip(_COEFFICIENTS, _POWERS))
    return CRITICAL_PA * math.exp(CRITICAL_K / temperature_K * series)


def saturation_temperature(pressure_Pa):
    """Saturation temperature in kelvin for an absolute pressure in Pa (bisection)."""
    if not saturation_pressure(TRIPLE_K) <= pressure_Pa <= CRITICAL_PA:
        raise ValueError('Pressure outside saturation range')
    low, high = TRIPLE_K, CRITICAL_K
    for _ in range(70):
        mid = (low + high) / 2
        if saturation_pressure(mid) < pressure_Pa:
            low = mid
        else:
            high = mid
    return (low + high) / 2
