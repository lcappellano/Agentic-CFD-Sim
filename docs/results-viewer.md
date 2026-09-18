# 3D results viewer

The driver exports every stopped case to `runs/<run>/results-viewer/<case>-<time>/`.
Serve it read-only on loopback:

```bash
.venv/bin/python tools/workbench.py results-serve runs/<run>/results-viewer/<export> --run runs/<run> --port 8766
```

Rotate with the middle mouse button, pan with Ctrl+middle or right button, zoom
with the wheel, probe with a left click. Fields: temperature, absolute pressure
(bar), speed. Solid surfaces are transparent; nine internal slices show saved
cell values. The header shows the case status (`diagnostic` / `numerically_screened`).

Manual export of another time or case:

```bash
.venv/bin/python tools/workbench.py results-export runs/<run> --case cases/case-xxxx --time 2000 --output runs/<run>/results-viewer/manual-1
```

Serving re-verifies the payload hash and every source hash against the run; a
changed case refuses to serve. Browser checks: `src/results/browser_smoke.py`
(needs Playwright; see memory/manager.md for the Chromium paths).
