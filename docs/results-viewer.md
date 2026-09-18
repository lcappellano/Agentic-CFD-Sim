# Final 3D simulation results

The read-only results viewer displays saved copper and water fields from the
accepted demo baseline. Open http://127.0.0.1:8766 while its server is running.
The initial requirements viewer remains separate on port 8765.

## Inspect the result

- Hold the middle mouse button (scroll wheel) and drag to rotate. Hold Ctrl
  with middle-drag to pan; right-drag also pans. Scroll to zoom and left-click
  to probe. Press **F** or Fit to frame the part without changing its orientation;
  **Home** restores the fitted isometric view. Seven buttons provide isometric,
  front, back, top, bottom, left and right views.
- Free arcball rotation passes through top and bottom without an upright-axis
  lock. Drag near the center for tumbling; dragging around the outside rolls the
  view. Motion stops immediately on release. The orthographic camera keeps
  parallel edges parallel and zoom is bounded.
- Select temperature (°C or K), pressure (bar gauge or absolute), or speed (m/s).
  Gauge pressure uses the stated ambient reference, 1.01325 bar for this run.
- Hide the solid or reduce its opacity to see the passage. Select an internal
  X, Y or Z slice at one of three saved positions; optionally show mesh edges.
- Click a displayed triangle to inspect its field value, coordinates and source
  face or cell identifier. The legend follows the displayed field and surfaces.
- Read the temperature-limit comparison, numerical acceptance and model
  qualifications alongside the model. The report link opens the full run report.

The current result is `case-hex-fine-corrected`, saved iteration `2000` in
`runs/20260917T231138-demo-baseline-7716aa5b`. Iteration is a steady solver index,
not elapsed physical time. The heated-face maximum is 308.25175 K (35.10 °C),
below the approved 500 K limit. Acceptance retains the documented inlet-row
wall-model qualification; it does not imply experimental validation.

These button mappings follow the [SOLIDWORKS mouse controls](https://help.solidworks.com/2019/english/SolidWorks/sldworks/r_middle_mouse_button.htm).
Navigation uses locally pinned [Three.js ArcballControls](https://threejs.org/docs/pages/ArcballControls.html)
version 0.180.0 with a stable part-center pivot, rather than reproducing every
SOLIDWORKS rotation mode. Rendering occurs on changes instead of continuously
redrawing the static solution.

## Launch and export

From the workspace root, start the existing export:

```bash
.venv/bin/python tools/workbench.py results-serve runs/20260917T231138-demo-baseline-7716aa5b/results-viewer/v1 --port 8766
```

Keep that terminal and WSL running. VS Code also provides **Workbench: serve
results viewer**. To create a fresh export from a supported reviewed run:

```bash
.venv/bin/python tools/workbench.py job --label results-export --input src/results/export.py --input runs/20260917T231138-demo-baseline-7716aa5b/verification-decision.json -- .venv/bin/python tools/workbench.py results-export runs/20260917T231138-demo-baseline-7716aa5b
```

The command prints the new export directory and launch command. Exports never
overwrite an existing directory. If an export is moved outside its original
`RUN/results-viewer/VERSION` layout, pass `--run RUN` to `results-serve`.

## Data and limits

The exporter reads actual saved OpenFOAM fields and mesh geometry. Boundary
triangles carry face values; internal slices intersect fluid cells and carry
piecewise constant cell values. They are not interpolated streamlines or a
transient animation. Pressure and speed are available only in the fluid;
temperature is available in both regions. Coordinates are displayed in mm;
exported fields retain SI units and display conversions happen in the browser.

The current adapter supports the canonical ASCII hexahedral demo result only.
Other geometries, cases or field layouts need a reviewed adapter. Export and
serving verify hashes against the acceptance evidence and source files. Missing,
modified or stale sources are rejected. The server binds to loopback and exposes
only allowlisted read-only resources; controls never modify the simulation.

Runtime uses the Python standard library and existing locally vendored Three.js.
Optional browser test dependencies are pinned in `requirements-dev.txt`;
Playwright's matching Chromium and operating-system browser libraries must also
be installed for browser tests. They are not needed to use the viewer.
