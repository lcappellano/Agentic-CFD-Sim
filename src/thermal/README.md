# src/thermal

| module | role |
| --- | --- |
| `materials.py` | named material library (copper, aluminum_6061, stainless_316; water) → material basis JSON |
| `liquid_water.py` | IAPWS SR6-08 liquid water at 0.1 MPa |
| `saturation.py` | IAPWS SR1-86 saturation curve |
| `fit_water_transport.py`, `check_transport_pressure.py` | CoolProp polynomial μ(T), k(T) fits and pressure sensitivity sampling |
| `operating_screen.py` | bulk energy-balance and saturation screen for candidate flows |
| `pump_budget.py` | idealised reservoir-to-part pump rise from saved port total pressures |

Add materials here with a source. Do not write run-local property scripts.
