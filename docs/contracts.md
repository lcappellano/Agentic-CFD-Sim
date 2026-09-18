# File contracts

## Approved handoff (`runs/<review>/handoffs/revision-<n>-<id>/`)

`source.step`, `model.json` (display faces, port candidates, import fingerprint),
`requirements.json` (selections + physical values), `approval.json` (user
confirmation bound to source/model/draft hashes), `project.json`, `manifest.json`.
`review-verify` checks the package. Approval authorises geometry preparation;
it says nothing about geometry validity or results.

## Simulation spec (`specs/*.json`)

See `docs/pipeline.md`. Only `handoff` is required; units may be L/min, bar, °C.

## Geometry manifest (`geometry/geo-*/manifest.json`, schema 2)

SI units, source and file hashes, `regions` (material, volume, OCC tag, file),
`boundary_map` (inlet, outlet, heated, outerWalls, interface with tags, areas,
centroids), `ports` (per-port area, centroid, outward normal, hydraulic diameter),
`port_outward_normals`, `port_hydraulic_diameter_m`, `heated_area_m2`,
`heated_to_passage_distance_m` (ligament under the heated face),
`approved_identity_map`, `checks`.

## Mesh metadata (`mesh/mesh-*.json`)

Geometry manifest hash, mesh hash, Gmsh version, element counts per region,
resolved sizing. Boundary layers: none.

## Material basis (`materials/basis-*.json`, schema 2)

`solid`, `fluid` names; `fluid_properties` at the inlet reference state;
`solid_properties`; `transport_model` (`constant`/`polynomial`) and optional
`transport_polynomials` (eight ascending-power coefficients, fit range, errors); sources.

## Prescreen (`prescreen/sweep-*.json`, `.md`)

Equivalent-duct model and its sources, sweep options, per-flow rows (velocity,
Reynolds, regime, pressure drop split, outlet temperature, wall and heated
temperature `spread`/`peak`, minimum outlet pressure), the flow × pressure
matrix (wall subcooling, idealised pump rise), the suggested starting point,
warnings and assumptions. `status: correlation_estimate` always.

## Case (`cases/case-*/`)

`settings.json` (every physical and numerical value, derived quantities, profile
name), `basis.json`, `geometry-manifest.json`, `acceptance-criteria.json`,
`manifest.json` (input hashes, execution status, solver logs, initialisation
records), `bounded-review.json` (per-chunk gates, stop reason),
`summary*.json`, `audits/fields-<t>.json`, `audits/history-<t>.json`.

## Run state (`state.json`) and report

Stage statuses, cache keys, outputs, one-line summaries, `case` result block
with `status` ∈ {`diagnostic`, `numerically_screened`, `accepted`}, stop reason,
key numbers, failed checks, viewer path, warnings, event log. `report.md` is
generated from it. `accepted` requires a human-written `decision.json`.

## Viewer export (`results-viewer/<case>-<time>/`)

`results.json` (triangles in mm with saved face/cell values), `summary.json`,
`manifest.json` (payload and source hashes). `results-serve` re-verifies hashes
against the run before serving.

## Specialist return

Status from `state.json` verbatim, files changed, the stop reason, what was
fixed in code, and the next spec change to try. No large data in the message.
