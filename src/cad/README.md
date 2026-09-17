# CAD intake and geometry handoff

Status: STEP **display import** is implemented in step_preview.py using the pinned
Gmsh API and local OpenCASCADE backend. It produces per-face display triangles and
unconfirmed circular port-cap candidates for the requirements viewer. Synthetic
display fixtures are included. Fluid-domain extraction, physical boundary
verification and simulation geometry export remain unimplemented.

Before downstream CAD preparation, read docs/requirements-review.md and verify
the user-approved package with tools/workbench.py review-verify. Consume the
copied source and exact import-bound boundary IDs; virtual disks are proposals
whose topology/closure still need verification. No user approval is inferred
from successful display import.

## Task inputs from the manager

- A versioned input CAD path and SHA-256 hash. Preserve the original file.
- Declared CAD units, expected dimensions, coordinate frame and any intended
  transforms. A file extension alone does not resolve units.
- Identification of inlet, outlet and heated surfaces using annotated views,
  named faces, or geometric descriptions that can be checked against the CAD.
  Record unresolved identities; do not guess from transient face numbers.
- Solid material regions, intended coolant passage and whether it is enclosed,
  connected, or includes separate circuits. The thermal specialist supplies
  material-property requirements; the CAD handoff maps materials to regions.
- Allowed geometry changes, output run directory, objective and acceptance
  criteria. `project.json` defaults to no geometry changes.

Use the manager's run plan to record units and other details not represented by
the current project schema. Input completeness does not establish CAD validity.

## Execution sequence for a future authorized run

1. Read `docs/contracts.md`, `memory/cad.md` and the assigned run plan. Inspect
   doctor evidence and verify the chosen CAD backend's actual version before
   implementing an adapter. Record executable probes and engineering scripts
   through `tools/workbench.py job`; coordinate use of its single-job lock.
2. Inspect a copy of the input, identify source solids and passage topology, and
   resolve face identities with the manager. Stop dependent work if these remain
   ambiguous. Do not heal or change geometry silently.
3. Produce repeatable scripts under `src/cad/` and versioned outputs under the
   assigned run's `geometry/`. Export both coolant and solid domains.
4. Write `geometry/manifest.json` with the evidence below and return a compact
   status report to the manager. A later geometry revision requires renewed
   boundary identification and all affected checks.

## Handoff acceptance checklist

The manifest must follow `docs/contracts.md`: schema version; source and output
hashes; backend and export versions; units, coordinates and transforms; file
paths; named regions, material assignments and volumes; heated area; inlet,
outlet, heated and other wall identities; and paired solid-fluid interfaces.

For each check, record pass, fail, or not-checked with evidence and tolerance:

- All intended fluid and solid regions have positive volume and valid,
  watertight boundaries in the selected representation.
- Coolant connectivity agrees with the intended circuit; inlet and outlet
  belong to that circuit, with no unintended gaps, leaks or disconnected pockets.
- Fluid and solid interiors do not overlap; their interface locations and areas
  agree within the recorded geometric tolerance.
- Boundary labels uniquely identify the intended surfaces, are disjoint where
  required, and cover the exported region boundaries without unexplained faces.
- Heated-face identities and total area agree with the user's specified loading;
  material assignments cover every region.

Failed or missing checks block acceptance of the geometry handoff. Meshing
quality and CFD boundary-condition verification remain downstream tasks.

## Current limits

The first supported geometry must be established with a reproducible benchmark
and reviewed before adaptation to user STEP files. Arbitrary STEP imports,
automatic passage closure/extraction, assembly healing, thin gaps, nonmanifold
geometry, multiple circuits, and automatic heated-face recognition currently
have no verified support. STEP exchange does not preserve SolidWorks feature
history. Unsupported input must receive an explicit limitation report, not an
assumed successful conversion.

Return: status, changed files, artifact paths, checks and tolerances, assumptions,
remaining defects, and the next blocking input. Keep full geometry data on disk.
