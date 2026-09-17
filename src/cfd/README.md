# Fixed-demo CHT adapter

`demo_case.py` builds an **OpenCFD OpenFOAM v2412 patch260127** steady
`chtMultiRegionSimpleFoam` case from the verified demonstration mesh. This is
not an arbitrary STEP-to-CFD adapter. It fixes the approved demo operating point:
water 0.5 kg/s, inlet300 K, outlet111325 Pa absolute, heated-face flux100000 W/m²,
copper, and adiabatic other exterior surfaces. Exact property provenance is
provided by the run's `thermal/estimates.json` and `thermal/engineering_basis.md`.

Source `/usr/lib/openfoam/openfoam2412/etc/bashrc` before invoking the project
recorder. Use the root `.venv/bin/python` for all project Python scripts:

```
.venv/bin/python tools/workbench.py job --label case-build --input src/cfd/demo_case.py --input RUN/geometry/meshes/MESH.msh --input RUN/thermal/estimates.json -- .venv/bin/python src/cfd/demo_case.py RUN/case-NAME RUN/geometry/meshes/MESH.msh --properties RUN/thermal/estimates.json --iterations 2500
.venv/bin/python tools/workbench.py job --label case-solve --input src/cfd/run_demo_case.py --input RUN/case-NAME/manifest.json -- .venv/bin/python src/cfd/run_demo_case.py RUN/case-NAME
.venv/bin/python tools/workbench.py job --label case-summary --input src/cfd/summarize_demo.py --input RUN/case-NAME/manifest.json -- .venv/bin/python src/cfd/summarize_demo.py RUN/case-NAME
```

The mesh must contain cellZones `fluid`/`solid` and boundary physical groups
`inlet`, `outlet`, `heated`, `outerWalls`, with a conformal shared interface.
`splitMeshRegions` creates mappedWall coupling patches. Mesh length units are m.
No CAD modifications are made by this adapter; finite mesh facets approximate
curved surfaces. The case manifest binds the CAD/mesh/property/approval inputs.

Pressure `p` and `p_rgh` have dimensions of Pa; with zero gravity both are
absolute static pressure. Pressure drop is the difference of area-averaged
port static pressure. The uniform mass-flow inlet produces developing flow;
no inlet reservoir or external fittings are modeled. k-epsilon RANS uses
standard velocity wall functions and Jayatilleke thermal wall functions.
Their applicability requires measured y+ evidence, not just requested mesh size.

`run_demo_case.py` rejects checkMesh without `Mesh OK` and records solver logs.
Successful execution is not numerical verification. `summarize_demo.py` reads
ASCII final fields and monitoring, checks matching timestamps, and accounts
for sensible enthalpy plus kinetic energy flux. For the aligned extruded hex
meshes, inlet thermal diffusion is integrated from actual boundary diffusivity
and the exact orthogonal normal temperature gradient; outlet diffusion is zero.
For other mesh types this correction is unavailable and explicitly marked.
Solid diffusion uses full nonorthogonal correction, least-squares gradients
and three nonorthogonal correction passes; fluid schemes remain separately
configured. Use `--ranks 4` with the solve script for local MPI, including
recorded decomposition and reconstruction. Liquid constant-property enthalpy
cpT does not include pressure-dependent enthalpy. User conclusions require
independent verification, mesh sensitivity, phase-applicability checks and
explicit engineering assumptions.

Reference examples are the installed v2412 `externalCoupledHeater`, `cpuCabinet`
and `buoyantSimpleFoam/comfortHotRoom` tutorials. Do not copy cases from a
different OpenFOAM distribution without verifying syntax and model semantics.
