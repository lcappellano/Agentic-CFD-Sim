# Superseded modules

Replaced by generalized modules in `src/`:

- `extract_closed_passage.py` → `src/cad/extract_passage.py` (ports at any orientation)
- `audit_manifold_geometry.py` → `src/verification/audit_geometry.py` (handoff based, no run-specific checks)
- `operating_screen.py` → `src/thermal/prescreen.py` (full flow and pressure sweep with correlations)
