# Thermal notes

- Water at 0.1 MPa from IAPWS SR6-08 (`liquid_water.py`, 273.15–383.15 K); CoolProp IAPWS-95 for polynomial μ(T), k(T) fits (`fit_water_transport.py`). Density and cp stay constant; sampled errors over 1–9 bar were ≲0.5 % for μ/k and up to 11 % for constant density near 440 K.
- Boiling screening must use wetted-wall temperature with local absolute pressure, not the heated-solid limit or a port-average Δp. A positive local pressure does not imply single-phase validity at the wall.
- Component total-pressure loss omits outlet jet dissipation; for equal-elevation open reservoirs the idealised pump rise is inlet total pressure minus suction pressure (`pump_budget.py`).
- Correlation screens (Gnielinski etc.) are not a maximum heated-face temperature for short, one-sided heating; use them only to choose flows to simulate.
- Prescreen bracket: for the manifold at 40 L/min the spread bound (mean wetted flux) lands near the CFD heated maximum; the peak bound is several times higher. Treat the bracket as a range for choosing sweep points, not as a prediction. Minor-loss coefficient 2.5 on the port dynamic pressure gave the right order of pressure drop for that manifold; tune per part family.
