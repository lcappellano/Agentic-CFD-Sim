# Reusable simulation pipeline

A run is data: approved CAD/requirements, explicit user overrides, material basis,
mesh settings and operating-point settings. Python modules in `src/` implement
operations. Agents review inputs and evidence, not individual solver iterations.

## Modules and contracts

| Stage | Reusable implementation | Inputs and outputs |
| --- | --- | --- |
| Intake | `requirements/review.py`, STEP preview | Versioned user selections and immutable CAD handoff |
| Region extraction | `cad/extract_closed_passage.py` | Reviewed solid and opposed end ports → exact solid/fluid BREP and boundary manifest |
| Mesh | `cad/mesh_regions.py` | Geometry manifest and mesh sizes → conformal MSH2 and quality/provenance metadata |
| Water properties | `thermal/liquid_water.py` | Temperature → sourced low-pressure liquid properties, with range guards |
| Transport fitting | `thermal/fit_water_transport.py` | Pinned CoolProp liquid data and declared range → polynomial viscosity/conductivity with fit errors and provenance |
| Property sensitivity | `thermal/check_transport_pressure.py` | Declared pressure/temperature range → sampled stable-liquid model errors; excludes vapor states |
| Fast screen | `thermal/operating_screen.py` | Resolved specification, geometry, properties, flows → energy/phase screens |
| CHT case | `cfd/cht_case.py` | Mesh, explicit configuration, material basis → OpenFOAM region dictionaries |
| Flow initialization | `cfd/initialize_velocity.py` | Fresh case → potential-flow velocity field with preserved physical boundary conditions and provenance |
| Execution | `cfd/run_case.py` | Built case and ranks → mesh checks, solver/reconstruction logs and fields |
| Numerical variant | `cfd/numerical_variant.py` | Reviewed same-mesh checkpoint → fresh case with an explicitly allowed numerical change and preserved physical state |
| Bounded continuation | `cfd/run_bounded.py` | Explicit iteration schedule → saved convergence/model gates; never automatic physical acceptance |
| Summaries | `cfd/summarize_case.py` | Saved monitoring/fields → diagnostic summary |
| Pump budget | `thermal/pump_budget.py` | Saved port total pressures and explicit reservoirs → idealized pump rise including discharge head |
| Search | `cfd/operating_search.py` | Reviewed operating evidence → bounded search support; never assume success means validity |
| Channel flow | `verification/channel_flows.py` | Tetrahedral field intersections and channel bins → signed branch fluxes and integration discrepancy |
| Verification | `verification/` | Independent geometry/field/convergence/mesh evidence; model applicability remains explicit |

The current cavity extractor supports one solid with opposed, axis-aligned circular
end ports; it is not an arbitrary STEP repair engine. It rejects unsupported or
ambiguous topology. Mesh generation does not imply sufficient near-wall resolution.
The general CHT builder supports constant properties and optional temperature-dependent
polynomial transport, with constant density and heat capacity. Both use a single-phase
model whose applicability must be reviewed for every case. The polynomial path passed a short native OpenFOAM v2412 startup; this establishes
dictionary compatibility, not physical validity or convergence. The simple screening correlation
is not a pressure-dependent high-pressure model; the optional transport fit uses
a declared reference pressure and still requires a pressure-sensitivity review.

## Running a new case

1. Import and visually approve the requirements. Preserve this receipt unchanged.
2. Record any explicit later user corrections separately in `user-overrides.json`;
   build `resolved-project.json` from the receipt plus those corrections.
3. Extract/check geometry, evaluate properties and screen proposed operating points.
4. Generate a fresh mesh and case from explicit settings. Record every compute
   invocation using `tools/workbench.py job --input ... -- COMMAND`.
5. Execute and review one baseline. Reuse the same scripts and geometry for later
   mesh/operating points; give each output a new versioned directory.
6. Search only where the numerical and physical model is adequate. Record failed
   cases and unresolved limits; do not turn a diagnostic into an accepted result.

Historical demo adapters remain unchanged as reproducibility references. New
modules remove their geometry/temperature/flow constants from runtime inputs.
Support contracts are narrow and documented; a new geometry class may need one
reviewed adapter, but another operating point does not need regenerated source.

Full case fields stay local under `runs/`. `src.results.saved_case` extends the existing viewer to stopped tetrahedral CHT cases. It binds saved fields, case status and summary hashes, preserves diagnostic acceptance labels, and reuses the boundary/slice exporter. Example: `.venv/bin/python -m src.results.saved_case RUN --case cases/CASE --time 2000 --output RUN/results-viewer/v1`. Serve with `tools/workbench.py results-serve EXPORT --run RUN --port 8768`. The canonical demo exporter retains its original guards.
