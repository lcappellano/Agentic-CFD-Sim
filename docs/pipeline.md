# Simulation pipeline

One spec in, one run out. The agent writes a small JSON spec; the driver does
the rest and records everything in the run directory.

```bash
.venv/bin/python tools/workbench.py simulate specs/my-part.json          # new run
.venv/bin/python tools/workbench.py simulate specs/my-part.json --run runs/<run>   # continue / rerun
.venv/bin/python tools/workbench.py status runs/<run>                     # < 1 KB summary
```

Stages: `handoff → geometry → materials → prescreen → [autofill or operator decision] → mesh → case → solve → audit → export → report`.
Each stage keys on a hash of its inputs (files, settings, and its own source).
Rerunning with an unchanged input skips the stage; changing `schedule.maximum`
only extends the solve; changing the mesh profile re-meshes and rebuilds the case.
`--until mesh` stops early. `--dry-run` prints the resolved spec.

## Prescreen, autofill and the operator decision

`tools/workbench.py prescreen specs/<part>.json` (or `simulate`, which runs it
anyway) sweeps flow and outlet pressure with duct correlations before any mesh
exists. It takes seconds and prints a table plus an estimated operating point:

- per flow: mean velocity, Reynolds number and regime, pressure drop (Petukhov
  friction plus a lumped minor-loss coefficient), outlet bulk temperature, wall
  and heated-face temperature as a `spread` / `peak` bracket, and the minimum
  outlet pressure that keeps the wall subcooled by the margin;
- per flow and outlet pressure: wall subcooling and the idealised pump rise;
- the estimated operating point (`src/thermal/autofill.py`): the smallest flow
  whose spread-bound heated-face temperature uses at most 75 % of the allowed
  rise above the inlet (`prescreen.autofill_temperature_fraction`), raised if
  needed until the wall stays subcooled by the margin at the preferred outlet
  pressure (the fixed or lowest review pressure, else atmospheric) while the
  velocity stays within `prescreen.plausible_velocity_m_s` (10 m/s); past that
  the outlet pressure makes up the rest (saturation pressure at wall plus
  margin, rounded up to 0.5 bar). Flows round up to two significant figures.
  A review lower bound raises a value; nothing is ever lowered or clamped.
  The sweep is centred on this estimate when the spec and the review give no
  range.

Plausibility is a check, not a cap. When the estimate needs more than
`plausible_velocity_m_s`, `plausible_outlet_pressure_Pa` (10 bar) or
`plausible_pressure_drop_Pa` (5 bar), exceeds a review upper bound or the pump
limit, or no point exists, the driver stops with `awaiting_operator_decision`
and prints the estimate with its `STOP:` reasons instead of running CFD. To run
the estimate anyway, copy its values into `operating`; to let autofill continue,
raise the threshold in `prescreen`. Values fixed by the review or the spec only
get warnings. Designs that push wear or pressure limits are therefore never
silently reshaped: the sweep and the estimate show what the physics asks for and
the operator decides.

Flow and outlet pressure are optional everywhere. When the spec has no
`operating.volume_flow_L_min` (or `mass_flow_kg_s`) or no outlet pressure and the
review left them blank, the driver fills the open values from the estimate,
records them in `state.autofill` and the report (the operating table marks them
"estimated by the prescreen"), and continues to CFD. Equal review bounds fix a
value; a lower bound raises the estimate; an upper bound the estimate exceeds
stops the run. The driver also stops with `status: awaiting_operator_decision`
when `decision.required: true` is in the spec (a human wants to choose from the
table) or when the estimate carries `stop` reasons (plausibility, bounds, pump
limit, or no feasible point). Then the operator picks a point, the agent writes it into `operating`
(optionally with a `decision` block naming who chose it and why), and
`simulate --run runs/<run>` continues from cache. The equivalent duct is
`D_h = 4V/A_wetted`, `L` = inlet-to-outlet centroid distance, `u = Q·L/V`;
override `hydraulic_diameter_m`, `flow_path_length_m`, `solid_thickness_m` or
`minor_loss_coefficient` in `prescreen` when the part is known better. The
bracket is a correlation estimate, not a prediction; expect the spread bound to
be nearer the CFD result for copper.

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
  "prescreen":  {"flow_range_L_min": [1, 50], "points": 8, "outlet_pressures_bar": [1.01325, 2, 4, 8],
                 "minor_loss_coefficient": 2.5, "wall_subcooling_margin_K": 10, "supply_pressure_Pa": 101325,
                 "flow_path_length_m": null, "hydraulic_diameter_m": null, "solid_thickness_m": null,
                 "autofill_temperature_fraction": 0.75, "plausible_velocity_m_s": 10,
                 "plausible_outlet_pressure_Pa": 1000000, "plausible_pressure_drop_Pa": 500000},
  "decision":   {"operator": "name", "note": "why this point was chosen from the prescreen",
                 "required": false,                     "// true": "stop after the prescreen for a human choice"},
  "initialization": {"temperature_from_case": "runs/<run>/cases/case-xxxx",
                     "fields_from_case": "runs/<run>/cases/case-xxxx",  "// restart": "every shared field from a settled case on the same mesh",
                     "fields_mapped_from_case": "runs/<run>/cases/case-xxxx",  "// mesh change": "solved fields mapped onto this mesh (mapFields)",
                     "temperature_from_prescreen": false},
  "unapproved_handoff_ok": false,
  "notes": "free text"
}
```

Only `handoff` is required. Leave the flow and outlet pressure out to get the
prescreen table and a stop for the operator. Materials default to the handoff's names; `transport`
is `constant` or `polynomial` (CoolProp fit; needs `fit_range_K` and
`reference_pressure_Pa`). Profiles live in `src/pipeline/profiles/`:

| kind | profiles |
| --- | --- |
| mesh | `tet-coarse`, `tet-medium`, `tet-fine`, `tet-test` (sizes scale with inlet hydraulic diameter; `*_m` overrides are absolute). Overrides also take `algorithm_3d` (1 serial Delaunay, 10 parallel HXT: use it above a few million cells), `threads`, `min_quality` (SICN floor, default 0.01) and `optimize_netgen`. Every mesh is checked against the floor before a case is built; a Netgen pass runs first when the floor is missed, and the metadata records the per-region minimum and worst location. |
| numerics | `tet-robust` (SST + Spalding, potential-flow start), `tet-robust-slow-energy`, `tet-robust-restart` (unlimited solid gradient; only from a settled checkpoint via `initialization.fields_from_case`), `hex-kepsilon`, `laminar` (chosen automatically when the prescreen regime at the operating point is laminar and the spec names no profile) |
| acceptance | `project-screening`, `test-loose` (tests only) |

Add a profile when a new class of part needs different defaults; do not put
numbers in prose. Solid names are looked up in `src/thermal/materials.py`
(`copper`, `cucrzr`, `aluminum_6061`, `stainless_316` and their aliases); add an
entry with its source there rather than typing properties into a spec.

## Restarting a settled case under changed numerics

A residual floor with settled temperatures and balances (the report says so in
its next step) is removed by a restart, not by more iterations. Point a new spec
at the settled case on the same mesh and name the numerics that fix the floor:

```json
"numerics": {"profile": "tet-robust-restart"},
"initialization": {"fields_from_case": "runs/<run>/cases/case-xxxx"}
```

`simulate <spec> --run runs/<run>` reuses the mesh, builds a new case with the
new schemes, copies every field the two cases share (U, p, p_rgh, T and the
turbulence fields; never phi) into its `0/` and skips the potential-flow start.
The operating point and the mesh must be identical; the seeded case is a new
case with its own gates, and nothing from the source's status is inherited.
`src.cfd.warm_start` does the same from the command line (`--all-fields`).

For a mesh change (a refinement pair, a new box) use `fields_mapped_from_case`
instead: `src.cfd.map_fields` runs OpenFOAM `mapFields -consistent` region by
region from the solved coarse case onto the new mesh and skips the potential-flow
start. On fine tetrahedral meshes the potential start resolves the singular
velocity at sharp corners as spikes that a steady start cannot damp; the mapped
start begins near the answer and needs a fraction of the iterations.

## Run directory

```
runs/<run>/
  spec.json  state.json  report.md  logs/<stage>.log
  handoff/                 copied approved package
  geometry/geo-<hash>/     solid.brep fluid.brep coupled.brep coupled.geo manifest.json audit.json
  mesh/mesh-<hash>.msh     + .json metadata
  materials/basis-<hash>.json
  prescreen/sweep-<hash>.json + .md   correlation sweep and table
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
| prescreen | `src.thermal.prescreen.prescreen(geometry, basis, operating, options)` and `markdown(...)` |
| case | `python -m src.cfd.cht_case CASE MESH --basis B.json --settings S.json --geometry M.json` |
| solve | `python -m src.cfd.run_bounded CASE --criteria C.json --maximum N` |
| audit | `python -m src.verification.audit_fields CASE --criteria C.json --output A.json`, `review_history`, `audit_geometry` |
| export | `python tools/workbench.py results-export RUN --case cases/X --time T --output RUN/results-viewer/x` |
| variants | `src.cfd.numerical_variant` (change relaxation on a checkpoint), `src.cfd.warm_start` (seed T, or every field with `--all-fields`, from a settled case), `src.verification.channel_flows` |
| design variants | `python -m src.cad.variants SOURCE.step OUT.STEP --fluid runs/<run>/geometry/geo-x/fluid.brep [--vanes-per-side 2 --vane-x-start 57 --vane-x-end 31]` (bullnose rib ends; header guide vanes; provenance JSON beside the output; `plan_section_svg` draws a plan section for review) |

The OpenFOAM environment is sourced automatically (`src/foam/environment.py`,
override with `OPENFOAM_BASHRC`). Never wrap commands in `bash -c "source ..."`.

## Design variants

`src/cad/variants.py` writes a new STEP from a reviewed one with the gmsh OCC kernel;
the input CAD is never modified and a provenance JSON (source hash, operations,
volumes) sits beside every output. Two operations exist because the manifold
results asked for them: `bullnose_rib_ends` fills the V-notch at the end of
each rib between channels and rounds the rib into a semicircle of its half-width,
and `header_guide_vanes` fuses thin vanes into a wide-angle header, dividing
its fan into sectors of equal width at the pipe end and at the collector end.
A variant is a new part: import it with `review-import`, select the ports and the
heated face, approve, and run it through the same specs and gates. The mapped
start (`fields_mapped_from_case`) needs identical geometry, so a variant starts
from a coarse mesh of its own.

## Known-result benchmarks

Everything in `runs/` comes from this code, so the only independent checks are
parts whose answer is measured. `src/pipeline/benchmarks.py` generates such a
part as an unapproved handoff (the run carries the synthetic warning; nobody
approves it): `smooth_tube_handoff` is a copper block with a straight round
bore, heated on top. Fully developed turbulent pipe flow is the best-measured
flow there is; `src/verification/duct_benchmark.py` fits the pressure gradient
over the developed part of the bore and the local Nusselt number from the
interface heat flux, and reports both against Petukhov's fit of the smooth-pipe
data and Gnielinski's correlation of the Petukhov-Kirillov data:

```bash
.venv/bin/python -c "from src.pipeline.benchmarks import smooth_tube_handoff; smooth_tube_handoff('inputs/benchmarks/smooth-tube-d2-l100')"
.venv/bin/python tools/workbench.py simulate specs/benchmark-smooth-tube-re26k.json
.venv/bin/python -m src.verification.duct_benchmark runs/<run>/cases/case-x --diameter 0.002 --output runs/<run>/cases/case-x/audits/duct-benchmark.json
```

The reference spec mimics the manifold channels (0.3 mm isotropic tetrahedra in
a 2 mm bore, wall functions at y+ about 50, Re 26 000). Rerun it after any
change to the wall treatment, the mesher or the numerics profiles.

## Limits

- One solid, one connected passage, user-selected planar circular ports (any orientation), steady single-phase liquid RANS, constant density and cp.
- Isotropic tetrahedra without prism layers; y+ is reported, not controlled. `snappyHexMesh` layers are the next step if wall resolution keeps failing gates.
- No boiling, cavitation, radiation or transient models.
