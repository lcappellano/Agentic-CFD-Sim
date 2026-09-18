# Cooling agent workbench

Drop a STEP file in, approve the ports and heated faces in a browser, write a
ten-line spec, run one command. The pipeline extracts the coolant passage,
meshes it, builds and runs a conjugate heat transfer case in OpenFOAM v2412,
audits the result independently and exports a 3D viewer.

```bash
.venv/bin/python tools/workbench.py doctor                       # toolchain
.venv/bin/python tools/workbench.py review-import --step inputs/part.step
.venv/bin/python tools/workbench.py review-serve runs/<review>   # user approves in the browser
.venv/bin/python tools/workbench.py review-handoff runs/<review>
.venv/bin/python tools/workbench.py simulate specs/part.json     # everything else
.venv/bin/python tools/workbench.py status runs/<run>
.venv/bin/python tools/workbench.py results-serve runs/<run>/results-viewer/<export> --run runs/<run>
```

A minimal spec:

```json
{"schema_version": 1,
 "handoff": "runs/<review>/handoffs/revision-6-xxxx",
 "operating": {"volume_flow_L_min": 40, "outlet_absolute_pressure_bar": 8},
 "numerics": {"profile": "tet-robust"},
 "schedule": {"maximum": 2000}}
```

Everything not in the spec comes from the approved handoff or a named profile.
See [docs/pipeline.md](docs/pipeline.md) for the full reference,
[AGENTS.md](AGENTS.md) for how the agents work, and
[docs/contracts.md](docs/contracts.md) for file contracts.

## Layout

| path | purpose |
| --- | --- |
| `src/pipeline/` | spec, profiles, driver, state, report |
| `src/foam/` | shared OpenFOAM readers, writers, environment, hashing |
| `src/cad/` | STEP preview, passage extraction, meshing |
| `src/thermal/` | material library, water properties, transport fits, screens, pump budget |
| `src/cfd/` | case settings, builder, runner, bounded driver, summaries, initializers |
| `src/verification/` | independent reader, field/geometry/history audits |
| `src/results/` | viewer export and server |
| `src/requirements/` | browser review of ports, faces and physical inputs |
| `legacy/` | frozen first-demo scripts; not imported |
| `docs/history/` | earlier narrative records |
| `runs/`, `inputs/` | local data, ignored by git |

## Setup

WSL2 Ubuntu, Python 3.10+, OpenCFD OpenFOAM v2412 (`/usr/lib/openfoam/openfoam2412`),
Gmsh 4.14 runtime, and `python3 -m venv .venv`. Optional: `requirements-engineering.txt`
(CoolProp for temperature-dependent transport) and `requirements-dev.txt`
(Playwright for browser checks). Tests: `tools/workbench.py test`; add
`WORKBENCH_E2E=1` to include the solver fixture (about a minute).

## Status

The pipeline was validated on the synthetic through-bore block and reproduces
the earlier manifold geometry extraction exactly. Earlier manual runs and their
evidence are described in `docs/history/`. Results carry an explicit status
(`diagnostic`, `numerically_screened`, `accepted`); nothing is experimentally validated.
