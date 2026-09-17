# STEP requirements review

The requirements specialist sits between the manager's initial intake and CAD
preparation. Give the manager a STEP path and describe the intended cooling and
heating in ordinary language. The manager delegates to this specialist, which
opens a local interactive review, proposes boundary assignments, and identifies
missing physical inputs. You inspect and correct the model before CAD handoff.

## What you see

- A rotatable, zoomable 3D part with clickable CAD faces and a keyboard surface list.
- **Blue inlet**, **green outlet**, and **orange heated solid surfaces**, with text
  labels. Inspect mode changes no assignments. Choose a role and click to assign;
  assigning another role replaces the previous one on that surface.
- **Purple candidate caps** over supported circular openings. These are visual
  proposals for fluid boundaries, not solid faces or changes to your source CAD.
  Transparent-solid and isolated-surface views help inspect hidden selections.
- Bounding dimensions in millimetres, selected area, heat flux or total power,
  temperatures, materials, flow and outlet absolute-pressure bounds, other thermal
  boundaries, and the objective. Heat enters the orange faces. The temperature
  limit applies to the maximum on those selected heated surfaces.

CAD cannot tell us the actual inlet direction, coolant, heating magnitude or
operating conditions. The agent uses your instructions and labels proposals for
you to confirm. Circular holes can be blind or unrelated to coolant; their actual
connectivity is a later CAD check. Spatial flow arrows are not inferred from the
arbitrary normal orientation of a fitted circle. The direction legend is explicit:
blue inlet → coolant passage → green outlet.

## Your review and handoff

1. Check the part and displayed dimensions. Rotate it and inspect the highlights.
2. Correct assignments and values if necessary; fill missing requirements or tell
   the manager what is unknown. The UI uses K, kg/s, bar and W or W/m².
   Select absolute or gauge pressure. Gauge input needs an explicit ambient
   reference in bar absolute; zero gauge is valid. The displayed conversion and
   saved source/reference distinguish gauge readings from solver absolute pressure.
   Canonical pressure values remain in Pa internally (1 bar = 100,000 Pa).
   Missing, zero-absolute and reversed bounds have distinct inline diagnostics.
3. **Save draft.** Drafts survive reloading; saving edits invalidates an earlier
   approval. Conflicting edits from another tab require reloading the saved draft.
4. When satisfied, enter your reviewer name, tick the explicit confirmation and
   click **Approve this review**. The agent never clicks this for a real user case.
5. Click **Create CAD handoff**, or tell the manager to continue from your approved
   review. The manager verifies the receipt and passes the package to CAD.

Only complete, current, explicitly approved requirements can be handed off.
Source STEP, imported display, selected boundaries and numerical values are
bound to hashes and a revision. A changed CAD/import needs a new review; altered
snapshot files block approval/handoff. An approval confirms your intended setup,
not geometry validity or a verified simulation.

The handoff copies the STEP, display model, requirements and approval, exports a
project.json, and records exact boundary identities and virtual-cap definitions.
CAD then validates the part, extracts solid/fluid regions and maps approved
selections onto actual fluid boundaries. Thermal, CFD and verification follow
the baseline-first workflow. No solver starts from the viewer.

## Local commands

The manager normally runs these. Put real CAD under inputs/; it is preserved.
The initial project.json may be incomplete. Supplied numeric/material values
seed the draft, but surface selections and scale always need visual confirmation.

```bash
python3 tools/workbench.py job --label requirements-import --input inputs/part.step --input project.json --input src/cad/step_preview.py --input src/cad/vendor/gmsh.py --input src/requirements/review.py --input tools/workbench.py -- python3 tools/workbench.py review-import --step inputs/part.step --label part-review
python3 tools/workbench.py review-serve runs/<review-directory>
```

Open the printed `http://127.0.0.1:8765` URL in your Windows or Linux browser.
The server binds to loopback only and serves bundled local assets; no CDN is
needed at runtime. Keep its terminal running; Ctrl+C stops the viewer. The viewer
service itself does no CAD computation, so it runs outside the single compute-job
lock. Use another port with `--port` if needed. WSL networking/browser access is
machine-dependent; the local Chromium browser test passed in this environment.

```bash
python3 tools/workbench.py review-status runs/<review-directory>
python3 tools/workbench.py review-handoff runs/<review-directory>
python3 tools/workbench.py review-verify runs/<review-directory>/handoffs/<version>
python3 tools/workbench.py prepare --project runs/<review-directory>/handoffs/<version>/project.json --label baseline
```

The last preparation verifies the approved package and archives its receipt in
the new run. Solver properties and acceptance settings are still unresolved;
preparation does not execute CAD or CFD. The current package uses absolute local
paths: retain the original package location. Archived copies preserve evidence
and hashes but are not directly reusable project locations without an explicit
path-migration feature. Never hand-edit a delivered package.

For agent-proposed assignments, `review-draft <directory> --draft proposal.json
--revision N` accepts exactly `{selections, requirements}` in the current schema.
It only saves proposals; there is deliberately no CLI approval command. The
interactive UI is the normal way to confirm. This is a local collaboration record,
not cryptographic identity proof or protection against a malicious local user.

## Demo and implementation

A synthetic block with a through bore is included at
src/cad/fixtures/cooling_block_through_bore_v1.step. It imports as one solid,
seven CAD faces, and two candidate circular port caps. The saved unapproved demo is
runs/20260917T215831-requirements-demo-634b5abf. Its physical values remain blank.

```bash
python3 tools/workbench.py review-serve runs/20260917T215831-requirements-demo-634b5abf
```

The new specialist definition is .codex/agents/requirements.toml. This session
ran a specialist named requirements with those instructions explicitly loaded;
a fresh Codex session can discover the new custom role. Model/access settings
are inherited. Four workers may run concurrently; requirements normally finishes
before downstream CAD, so five role definitions need no higher concurrency limit.

Display uses pinned [Three.js](https://threejs.org/docs/pages/Raycaster.html)
0.180.0 and its [OrbitControls](https://threejs.org/docs/pages/OrbitControls.html).
STEP reading, boundary geometry and display tessellation use
[Gmsh/OpenCASCADE](https://gmsh.info/doc/texinfo/) through the vendored Gmsh 4.14.0
Python wrapper and installed 4.14.0 runtime (this machine reports 4.14.0-git).
Licenses and source/hash provenance accompany the bundled files. There is no
application package installation or external browser asset dependency.

Initial scope: one solid/material, one coolant, steady conditions, uniform heating,
fixed geometry, one inlet and outlet set. Transient or nonuniform loads, assemblies,
independently controlled circuits, partial-face heating and noncircular/nonplanar
openings need an explicit extension or additional CAD preparation. No general
automatic feature recognition, passage extraction or solver adapter is claimed.
Face IDs are valid only for the recorded source/import fingerprint. Display
triangles are not a computational fluid mesh.

Browser tests used Playwright 1.58.0 and Chromium 145.0.7632.6 in /tmp, with the
Ubuntu 24.04 browser build on Ubuntu 26.04 and a temporary extracted audio library.
These are test dependencies, not required to use the viewer in your own browser.
See VALIDATION.md and the requirements setup review for evidence and test commands.
