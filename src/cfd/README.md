# CFD workflow and readiness

This directory is the CFD specialist's implementation area. No mesh generator,
CHT case adapter, solver driver, or engineering postprocessor has been implemented.
Setup discovery has not generated a mesh or executed a physical simulation.

## Local environment identified on 2026-09-17

- OpenCFD distribution, OpenFOAM v2412, package `2412.260127-1`, solver build
  `_b8cf4d35-20260127` (patch `260127`), double precision / 32-bit labels.
- Environment script: `/usr/lib/openfoam/openfoam2412/etc/bashrc`. The initial
  shell did not source it, so the initial doctor correctly found no solver on PATH.
- After sourcing, `blockMesh`, `snappyHexMesh`, `checkMesh`,
  `chtMultiRegionFoam`, and `chtMultiRegionSimpleFoam` resolve in the installation.
  Both CHT executables successfully displayed their help/version banners.
  Mesh executables were located only; no mesh command was executed.
- The transient and steady CHT tutorial trees are available under
  `/usr/lib/openfoam/openfoam2412/tutorials/heatTransfer/`. Future adapters must
  use this distribution's installed tutorials and documentation.
- `foamVersion`, `foamRun`, and `foamMultiRun` were not found in the sourced shell;
  do not use those commands as prerequisites for this installation.
- Package inventory also identifies Gmsh `4.14.0+ds1-1build4`, Open MPI
  `5.0.10-1`, and ParaView `6.0.1+dfsg1-7`. Package presence does not establish
  end-to-end runtime compatibility or validate any simulation.

Recorded evidence (relative to the repository root):

- `runs/20260917T213320-setup-doctor-e6b88608/console.log`
- `runs/20260917T213418-setup-cfd-discovery-4f17632d/console.log`
- `runs/20260917T213428-setup-cfd-version-30b58412/console.log`

The final probe's shell exit code alone is insufficient evidence for every
subcommand: its log explicitly records the missing `foamVersion` command.
Solver identity comes from the CHT help banners and package inventory. Source the
environment before invoking the job runner for future solver jobs so the runner
also records `WM_PROJECT_VERSION`; sourcing inside a child command leaves the
parent runner's version field null.

## Required handoff before a baseline

The manager assigns a versioned run directory and a resolved project specification.
The CAD specialist supplies a verified `geometry/manifest.json`, with geometry
hashes, units, solid/fluid regions, material assignments, inlet/outlet and heated
face identities, coupled interfaces, and connectivity/watertightness evidence.
Unresolved boundary identities or material properties block a physical solve.

The thermal specialist supplies material-property sources, inlet thermal state,
heat load, flow and absolute-pressure bounds, and model-applicability concerns.
The manager records the intended objective, allowable geometry changes, resource
limits, and numerical acceptance criteria. Initial work stays on fixed geometry.

## Future implementation sequence

1. Select a suitable installed v2412 tutorial as a dictionary reference and build
   a reusable adapter for the agreed reproducible benchmark. Review the fluid
   thermophysical model and whether a single-phase model is applicable.
2. Record `case/manifest.json` against the geometry manifest hash, including exact
   distribution/build, material sources, boundary conditions, meshing settings,
   numerics, and agreed convergence and balance thresholds.
3. Generate and inspect one baseline mesh; preserve the mesh-quality output.
   Check inlet/outlet connectivity, region interfaces, and heated patch identity.
4. Execute one baseline through `tools/workbench.py job`, with all relevant input
   files listed via repeated `--input`. Preserve commands, full logs, and fields.
   Do not equate a zero exit code with convergence. The runner serializes jobs.
5. Report maximum heated-surface temperature and location, target pressure drop,
   mass flow, coolant heat pickup, mass and energy imbalance, flow maldistribution,
   convergence histories, and mesh-sensitivity evidence. Unavailable quantities
   are null with a reason. Independent verification precedes any sweep.
6. Only after a reviewed baseline, use a script for a bounded operating-condition
   sweep. Adapt the verified pipeline to user STEP geometry incrementally.

For every selected solver, verify pressure-field dimensions and reconstruction
from its exact source/tutorials. Distinguish absolute, gauge, kinematic, and
hydrostatic-reduced pressure, as applicable, from inlet-to-outlet pressure drop.
Document the pressure averaging convention and elevations. A consistent example
is prescribed inlet mass flow and outlet absolute pressure; pressure drop is then
an output rather than an independently prescribed third boundary condition.

The present setup stops before step 1. No solver configuration, physical result,
convergence assessment, or arbitrary STEP-to-CHT automation is claimed.
