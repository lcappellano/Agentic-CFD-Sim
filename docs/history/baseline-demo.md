# Fixed demo CHT baseline

The first baseline uses the explicitly approved through-bore demo, not an arbitrary
STEP model. Its CAD adapter checks the 60 × 40 × 20 mm solid with an 8 mm through
passage before constructing the coolant region. The original STEP is preserved.

## Inputs and scope

The evidence directory is
`runs/20260917T231138-demo-baseline-7716aa5b`. Its `requirements_review/` contains
the immutable revision-8 receipt, source, face map and approved requirements.
`project.json` is the approved snapshot; `baseline-settings.json` records the
additional engineering assumptions and numerical acceptance criteria.
`resolved-project.json` combines these without modifying the approval receipt.

The baseline uses copper, water at 300 K, 100000 W/m² over the 0.0024 m² top face
(240 W), 0.5 kg/s coolant and 111325 Pa absolute outlet pressure. The displayed
outlet pressure is 0.1 bar gauge using a 1.01325 bar ambient reference. The user's
heated-surface limit is 500 K. No geometry changes or operating-point sweep are
part of this run. A second mesh tests numerical sensitivity at the same condition.

The unheated exterior is adiabatic with no external irradiation. Vacuum alone
does not imply this boundary condition. Constant copper/water properties and
smooth walls are explicit baseline approximations; see the run's
`thermal/engineering_basis.md` for sources and applicability.

## Local tools

Use the project `.venv/bin/python` for scripts. The present environment has
Python 3.14.4 and no system `ensurepip`; the environment was created with
`python3 -m venv --without-pip .venv`. These adapters use the Python standard
library plus the existing vendored Gmsh 4.14.0 wrapper and installed 4.14.0-git
OpenCASCADE runtime; no new Python package was installed.

OpenCFD OpenFOAM v2412 is installed at `/usr/lib/openfoam/openfoam2412`.
Source its `etc/bashrc` before running the job recorder so version metadata is
captured. The case uses `chtMultiRegionSimpleFoam`; installed-version tutorials
and actual solver checks, rather than a different OpenFOAM distribution's syntax,
are the reference. Full commands and input hashes are in recorded `job.json`
files indexed by the run's `workflow.json`.

## Reusable adapters

- `src/cad/prepare_demo_baseline.py`: validates the approved fixture, imports in
  metres, checks exact solid/fluid volumes and shell closure, verifies port
  outward normals and writes the geometry manifest. Use a fresh output directory.
- `src/cad/mesh_demo_baseline.py`: generates a conformal tetrahedral mesh with
  two material zones and local bore-wall refinement. No prism layers are added;
  solved wall-distance/yPlus evidence is required for wall-function use.
- `src/cad/mesh_demo_structured.py`: generates conformal hexahedral O-grids
  aligned with the bore. This became necessary after the initial tetrahedral
  mesh pair failed the pressure-drop sensitivity criterion. Shape and heated
  area remain fixed; circular faceting errors are reported explicitly.
- `src/thermal/demo_estimate.py`: provides heat/flow estimates and saturation
  screening. Correlations are not a substitute for the coupled solution.
- `src/cfd/demo_case.py`: builds this specific demo's OpenFOAM case from a mesh.
  Treat it as a fixture adapter, not a general simulation-specification reader.
- `src/cfd/summarize_demo.py`: extracts the executed case's numerical evidence.
- `src/reporting/plot_demo.py`: plots measured convergence and boundary-face
  temperatures using matplotlib bundled with ParaView 6.0.1. Invoke this one
  adapter with `pvpython --no-mpi --disable-registry`; that embedded plotting
  runtime is separate from the project Python environment.

Execute engineering commands through `tools/workbench.py job`; only one recorded
job runs at a time. Each replay must use new geometry/case output directories.
The manager coordinates specialists and records the selected artifacts, including
failed development attempts, in the run plan. Do not select an earlier incomplete
case or geometry just because its directory exists.

## Acceptance

Assess actual heated-patch maximum against 500 K and wetted-wall maximum against
water saturation at minimum absolute pressure. The additional 10 K saturation
margin is an engineering screen, not a film-boiling calculation. Check mass and
energy conservation, final-window stability, wall treatment and paired-mesh
sensitivity before accepting the result. Two meshes show observed sensitivity;
they do not establish formal grid independence or experimental validation.

Raw fields and run records remain local under the repository's existing ignore
rules. Keep that directory when preserving or transferring the complete evidence.

## Accepted result

The corrected aligned pair is accepted with model limits. At 0.501481 L/s and
0.1 bar gauge outlet pressure, the maximum heated temperature is 308.251748 K,
passage pressure drop is 0.0869754 bar, and wetted-wall saturation margin is 70.8218 K.
The unchanged CAD therefore meets the 500 K heated-surface limit under the recorded
assumptions. See the local run's report/report.md and verification-decision.json.
The automated near-wall flag and manual qualification are preserved explicitly.

Canonical cases are case-hex-coarse-corrected and case-hex-fine-corrected; the
fine mesh uses geometry/structured/fine-wall.msh. Earlier directories named
case-coarse-final and case-fine-final are rejected diagnostic tetrahedral cases.
Execution manifests remain frozen as pre-review records; the independent review
and manager workflow carry final acceptance. Source snapshots are in cfd-source/.
