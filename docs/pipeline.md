# Simulation pipeline

One spec in, one run out. The agent writes a small JSON spec; the driver does
the rest and records everything in the run directory.

```bash
.venv/bin/python tools/workbench.py simulate specs/my-part.json          # new run
.venv/bin/python tools/workbench.py simulate specs/my-part.json --run runs/<run>   # continue / rerun
.venv/bin/python tools/workbench.py status runs/<run>                     # < 1 KB summary
```

Stages: `handoff → geometry → mesh → materials → screen → case → solve → audit → export → report`.
Each stage keys on a hash of its inputs (files, settings, and its own source).
Rerunning with an unchanged input skips the stage; changing `schedule.maximum`
only extends the solve; changing the mesh profile re-meshes and rebuilds the case.
`--until mesh` stops early. `--dry-run` prints the resolved spec.

## Spec reference

```json
{
  "schema_version": 1,
  "handoff": "runs/<review>/handoffs/revision-6-xxxx",
  "label": "manifold-40lpm",
  "operating": {
    "volume_flow_L_min": 40,                 "// or": "mass_flow_kg_s",
    "outlet_absolute_pressure_bar": 8,       "// or": "outlet_absolute_pressure_Pa",
    "inlet_temperature_C": 10,               "// or": "inlet_temperature_K; default: handoff",
    "heat_flux_W_m2": 1e7,                   "// or": "total_heat_load_W; default: handoff",
    "temperature_limit_C": 200,              "// default": "handoff maximum_surface_temperature_K",
    "max_pump_pressure_rise_Pa": 800000,     "// optional": "audit check",
    "target_pump_pressure_rise_Pa": 600000,  "// optional": "reported only",
    "minimum_saturation_margin_K": 10
  },
  "materials": {"solid": "copper", "fluid": "water", "transport": "constant",
                "fit_range_K": [278.15, 440], "reference_pressure_Pa": 901325},
  "mesh":       {"profile": "tet-coarse", "overrides": {"refinement_boxes": []}},
  "numerics":   {"profile": "tet-robust", "overrides": {}},
  "acceptance": {"profile": "project-screening", "overrides": {}},
  "schedule":   {"initial": 100, "chunk": 500, "maximum": 2000, "ranks": 4},
  "initialization": {"temperature_from_case": "runs/<run>/cases/case-xxxx"},
  "unapproved_handoff_ok": false,
  "notes": "free text"
}
```

Only `handoff` is required. Materials default to the handoff's names; `transport`
is `constant` or `polynomial` (CoolProp fit; needs `fit_range_K` and
`reference_pressure_Pa`). Profiles live in `src/pipeline/profiles/`:

| kind | profiles |
| --- | --- |
| mesh | `tet-coarse`, `tet-medium`, `tet-fine`, `tet-test` (sizes scale with inlet hydraulic diameter; `*_m` overrides are absolute) |
| numerics | `tet-robust` (SST + Spalding, potential-flow start), `tet-robust-slow-energy`, `hex-kepsilon` |
| acceptance | `project-screening`, `test-loose` (tests only) |

Add a profile when a new class of part needs different defaults; do not put
numbers in prose.

## Run directory

```
runs/<run>/
  spec.json  state.json  report.md  logs/<stage>.log
  handoff/                 copied approved package
  geometry/geo-<hash>/     solid.brep fluid.brep coupled.brep coupled.geo manifest.json audit.json
  mesh/mesh-<hash>.msh     + .json metadata
  materials/basis-<hash>.json
  screen/screen-<hash>.json
  cases/case-<hash>/       OpenFOAM case, settings.json, basis.json, geometry-manifest.json,
                           bounded-review.json, summary.json, audits/, log.*
  results-viewer/<case>-<time>/   viewer export
```

`state.json` is the machine-readable record: stage status, keys, outputs,
one-line summaries, the case result and warnings. `report.md` is generated
from it. Neither is hand edited.

## Result status

| status | meaning |
| --- | --- |
| `diagnostic` | executed; a numerical or model screen fails. Values are not results. |
| `numerically_screened` | all numerical gates and the liquid-phase screen pass on one mesh. Mesh sensitivity, model applicability and review remain. |
| `accepted` | a reviewer wrote an explicit `decision.json`. Code never sets this. |

Stop reasons (`state.case.stop_reason`) and the suggested next action are in
`src/pipeline/report.py`. Nothing here implies experimental validation.

## Standalone modules

Every stage is also a module with a CLI, for diagnosis or reuse:

| stage | module |
| --- | --- |
| geometry | `python -m src.cad.extract_passage HANDOFF OUT` |
| mesh | `python -m src.cad.mesh_regions GEOMETRY OUT.msh --wall-size 4e-4 --bulk-size 1.6e-3` |
| materials | `src.thermal.materials.material_basis(...)`, `python -m src.thermal.fit_water_transport` |
| case | `python -m src.cfd.cht_case CASE MESH --basis B.json --settings S.json --geometry M.json` |
| solve | `python -m src.cfd.run_bounded CASE --criteria C.json --maximum N` |
| audit | `python -m src.verification.audit_fields CASE --criteria C.json --output A.json`, `review_history`, `audit_geometry` |
| export | `python tools/workbench.py results-export RUN --case cases/X --time T --output RUN/results-viewer/x` |
| variants | `src.cfd.numerical_variant` (change relaxation on a checkpoint), `src.cfd.warm_start`, `src.verification.channel_flows` |

The OpenFOAM environment is sourced automatically (`src/foam/environment.py`,
override with `OPENFOAM_BASHRC`). Never wrap commands in `bash -c "source ..."`.

## Limits

- One solid, one connected passage, user-selected planar circular ports (any orientation), steady single-phase liquid RANS, constant density and cp.
- Isotropic tetrahedra without prism layers; y+ is reported, not controlled. `snappyHexMesh` layers are the next step if wall resolution keeps failing gates.
- No boiling, cavitation, radiation or transient models.
