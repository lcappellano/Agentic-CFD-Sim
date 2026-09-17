# File contracts and extension points

## Project specification

project.json is deliberately incomplete. The manager fills it using the user's
request and records assumptions. Explicit SI suffixes prevent unit ambiguity.
Do not start a physical solve with unresolved heated faces or material properties.

The selected objective may be feasibility, minimum mass flow, or minimum pumping
power. Temperature compliance alone need not produce a unique operating point.
Specify flow and absolute-pressure search bounds separately. Treat target pressure
drop and whole-loop pump requirements as different outputs.

Schema 2 adds an alternative total_heat_load_W, inlet_faces, outlet_faces,
operating_mode, other_thermal_boundaries, material_properties (property models,
units and sources), and acceptance_criteria (tolerances and stopping conditions).
Exactly one heat-load representation is used by initial intake. Unknown physical
values remain null; the starter does not assume water or a particular objective.
The simple intake helper supports steady cases only. check validates structure,
not physical adequacy; material and acceptance objects need specialist review.

## Prepared request (workflow.json in a run)

The prepare command writes project.json, optional inputs/<original CAD name>,
workflow.json, and plan.md into a unique directory. Input entries record copied
paths, original workspace-relative paths and SHA-256 hashes. Use those copies
for downstream work. Intake issues and pending reviews are explicit; all stages
start not_started and simulation_executed is false. Preparation never runs CAD,
meshing, estimates or solvers. status rechecks copied-input hashes.

The manager owns workflow.json and plan.md, records later job-directory paths
in jobs, and updates stages only with evidence. This file is a handoff record,
not a scheduler or automatic execution gate. The generic job runner can execute
trusted commands directly; the manager remains responsible for honoring task scope.

## Requirements review and approved CAD input

See docs/requirements-review.md and src/requirements/intake-contract.md for the
user-facing sequence. The requirements agent prepares proposals; only the user
explicitly approves the current displayed draft before downstream CAD preparation.

A review directory contains inputs/source.step, model.json, review.json and plan.md.
model.json includes source/import hashes, Gmsh version/settings, mm units, dimensions,
solid count, original face IDs and display triangles, and distinct virtual circular
port candidates. Original source faces and proposed caps must never be conflated.
These are display assets, not CFD region geometry. Boundary IDs are import-specific.

review.json stores immutable-input hashes, the revisioned draft, and either null
approval or an explicit user confirmation with reviewer/time and source/model/draft
hashes. Editing a draft clears approval; stale writes and altered inputs fail.
Approval requires selected inlet/outlet/heat sets, confirmed scale, named materials,
inlet and heated-surface-limit temperatures, heat input, other thermal boundaries,
flow/absolute-pressure bounds and objective. Solver properties/numerical criteria
remain downstream engineering tasks. Initial mode is steady and fixed geometry.

The pressure UI uses bar, while canonical outlet_absolute_pressure_bounds_Pa
remains SI absolute pressure. Optional requirements.pressure_input preserves
mode (absolute/gauge), bounds_Pa in the input reference, and reference_pressure_Pa
(positive ambient absolute pressure for gauge, null for absolute). Legacy drafts
without metadata retain absolute semantics. Approval verifies conversion against
the canonical bounds; zero gauge is allowed if resulting absolute pressure is
positive. Handoff includes the input mode/reference for traceability.

Each handoffs/revision-<n>-<id>/ package copies source.step, model.json,
requirements.json, approval.json and exports project.json and manifest.json.
The manifest binds file hashes, approval, boundary roles and cap definitions.
review-verify cross-checks both hashes and physical-value/selection consistency.
prepare --project <handoff>/project.json verifies that receipt before archiving
it in a new run. Packages currently use absolute paths and must retain their
original location for reuse. Archived receipt copies are provenance only.

Approval authorizes CAD preparation of the intended case; it does not verify
passage connectivity, establish valid material properties, or authorize an
unrequested solver run. No automatic scheduling or human identity authentication
is provided by the local review service.

## Simulation geometry handoff (geometry/manifest.json in a run)

- Schema version and source file hash; tool and export versions.
- Units, coordinate frame, transforms, solid and fluid file paths and hashes.
- Material assignments, region volumes, heated area, and boundary identities.
- Inlet, outlet, heated walls, other walls, and coupled solid-fluid interfaces.
- Connectivity and watertightness checks with pass/fail/not-checked evidence.
- After a geometry change, explicitly revalidate boundary identification.

## Simulation handoff (case/manifest.json in a run)

- Geometry manifest hash; exact OpenFOAM distribution/version and solver.
- Mesh configuration and quality results; material properties and sources.
- Heat load, inlet state, outlet condition, other thermal boundaries, turbulence
  treatment, pressure variable definition, numerics, and convergence criteria.
- Command, runtime, exit code, logs, and paths to fields and summaries.
- Evidence: maximum heated-wall temperature and location; target pressure drop;
  mass flow; heat input/removal; balances; convergence; mesh sensitivity;
  phase-model applicability. Mark unavailable values null, with a reason.

## Specialist return

Use a short report: status, files changed, artifacts, evidence, assumptions,
remaining defects, and recommended next action. Keep large data on disk.
The reviewer must distinguish execution success, numerical verification, and
experimental validation. These are different claims.

## Runtime and future work

Codex provides the interactive manager, specialist threads, and tool permissions.
The folder provides their instructions, memory, engineering source, and run records.
tools/workbench.py is a small local process recorder, not an autonomous manager.
It records commands and specified input hashes but cannot automatically discover
every dependency. The caller must list all relevant input files.

STEP display import and requirements review are implemented. Simulation region
extraction, CFD and thermal adapters remain extension points. Implement these with one local
benchmark. Later add a persistent job service if unattended execution and automatic
manager wake-up are needed. Closing a chat does not make these instructions run
forever; a running client/service is required. WSL must remain awake during solves.

Agent file ownership is a coordination convention, not filesystem isolation.
Use separate worktrees if future tasks require overlapping code changes.
