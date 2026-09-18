# Manager notes (reusable lessons only; project narrative lives in each run's report.md and docs/history/)

- Environment: WSL2 Ubuntu, Python 3.14 in `.venv` (created `--without-pip`; pip installed later), OpenCFD OpenFOAM v2412 patch 260127 at `/usr/lib/openfoam/openfoam2412`, Gmsh 4.14.0 runtime with the vendored wrapper. `tools/workbench.py doctor` confirms. The pipeline sources OpenFOAM itself.
- Browser checks need `PLAYWRIGHT_BROWSERS_PATH=/tmp/cooling-browser-binaries` and `LD_LIBRARY_PATH=/tmp/cooling-browser-libs/extracted/usr/lib/x86_64-linux-gnu` (Chromium 1208 already extracted there).
- Users give flow in L/min and pressure in bar; the spec accepts those units directly. Ask whether a pressure is absolute, gauge, or a pump rise before writing the spec; do not guess. An outlet pressure is not a pump rise.
- Three of flow, outlet pressure and pump rise over-determine a case. Impose flow and outlet pressure; report the pressure rise against the target.
- The first real part (Astra manifold, September 2026) reached 111.6 °C heated maximum at 40 L/min and 8 bar absolute outlet on the tet mesh; pressure drift and residual gates failed, so it stays `diagnostic`. Its handoff is `runs/20260918T002459-astra-manifold-review-27f127f8/handoffs/revision-6-4824154e` and `specs/example-manifold-40lpm.json` reproduces the setup.
- Approvals: the requirements viewer is the only place a user approves; agents never call approve on a real case. Synthetic approvals live only in tests.
