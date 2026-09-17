# CFD notes

- 2026-09-17 setup: OpenCFD OpenFOAM v2412 is installed at
  `/usr/lib/openfoam/openfoam2412`; source its `etc/bashrc` before discovery/jobs.
  Package `2412.260127-1`; both CHT solver help banners report build
  `_b8cf4d35-20260127`, patch `260127`. Evidence:
  `runs/20260917T213418-setup-cfd-discovery-4f17632d/console.log` and
  `runs/20260917T213428-setup-cfd-version-30b58412/console.log`.
  Applies to this WSL installation; reconfirm if it changes.
- Initial doctor PATH absence did not mean OpenFOAM was uninstalled.
  `foamVersion` is absent; use the exact executable help banner/package record.
  Installed v2412 tutorials are the starting reference for future adapters.
- Source the OpenFOAM environment before starting the recorder if its parent
  version metadata must be populated. Child-only sourcing left that field null
  in the setup probe; detailed version evidence remains in the console log.
- Setup only: no mesh/solve/postprocessing executed and no CFD adapter exists.
  Next work is an explicitly authorized benchmark with a verified geometry
  manifest and resolved physical inputs, following `src/cfd/README.md`.
- 2026-09-17 baseline implementation, run `20260917T231138-demo-baseline-7716aa5b`:
  OpenCFD v2412 patch260127 `chtMultiRegionSimpleFoam` supports exact-demo
  Gmsh MSH2 cellZones via `gmshToFoam` then `splitMeshRegions -cellZones -overwrite`.
  Root fvSchemes must contain scheme dictionaries even during splitting.
  Solid `p` is required by heSolidThermo/rhoConst; solid symmetric h equation
  needs PCG/DIC, not DILU. Convert external solid patches to wall for wallHeatFlux.
  `-dry-run` simplified mesh failed on imported empty cellZones; full mesh solver
  startup worked after dictionary corrections. Preserve real checkMesh evidence.
- For water Pr~5.86 with wall-function y+~45–205, final baseline uses
  `compressible::alphatJayatillekeWallFunction`, as installed v2412
  buoyantSimpleFoam/comfortHotRoom tutorial and exact-version API specify:
  https://api.openfoam.com/2412/classFoam_1_1compressible_1_1alphatJayatillekeWallFunctionFvPatchScalarField.html
  Simple alphatWallFunction mut/Prt lacks the appropriate thermal-sublayer model;
  its exploratory case is retained but excluded from final mesh comparison.
  With g=0, both p and p_rgh are absolute pressure in Pa for this solver; not
  kinematic pressure. Compare total modeled h+K boundary fluxes as well as cpΔT.
- Same baseline, final numerical development: isotropic tetra meshes (89,708 vs
  234,070 cells) yielded converged pressure drops17.408 vs13.577 kPa and spurious
  local pressure undershoots. They failed hydraulic sensitivity and are diagnostic
  only. Axially aligned O-grid hex meshes eliminated undershoots and reduced the
  coarse pressure drop to8.643 kPa. Do not accept a low solver residual as mesh
  adequacy; retain checkMesh, near-wall evidence, and paired mesh comparisons.
- Solid O-grid max nonorthogonality~65deg exposed material bias from a limited0.5
  solid Laplacian: coarse heated Tmax307.612K at center changed to308.248K at edge
  with full corrected Laplacian/snGrad, leastSquares gradient and3 correction
  passes. Use full corrected solid diffusion for this adapter; fluid settings
  are independent. Confirm physical hotspot distribution in addition to scalar
  temperature compliance.
- Parallel v2412 multi-region decomposePar requires per-region decomposeParDict
  even when a root dictionary exists. Four local MPI ranks, followed by
  reconstructPar -allRegions -latestTime, markedly reduced elapsed runtime.
- Exact extruded-hex inlet is orthogonal to x, so inlet heat diffusion can be
  integrated from (k+cp*alphat)*(Tin−Towner)/(dx/2). Include saved alphat, which
  is appreciable at the turbulent inlet. This closed the coarse h+K budget;
  do not generalize the centroid-based calculation to arbitrary hexahedra.
- Final corrected pair in the same baseline run reached2000iterations each:
  `case-hex-coarse-corrected`79,872 cells and `case-hex-fine-corrected`241,920cells.
  Fine heated maximum308.2517477K, wetted304.9610399K, pressure drop8697.53994Pa,
  mass imbalance6.0e-13 and modeled energy imbalance9.28e-6 fraction after inlet
  diffusion. Mesh Tmax change0.00410K; pressure change0.625%. Applies only to
  this fixed demo/operating point/model. Final evidence is in case summary.json
  and run cfd-results.json plus independent verification records.
- Fine wall y+29.405–50.483:0.07685% wetted area lies just below nominal30, only
  in the first axial row. Manager/verifier accepted this as a documented narrow
  near-threshold limitation, not a hard physical discontinuity at y+=30.
  Original12-radial-layer fine mesh was not solved; final9-radial-layer variant
  refines axial/circumferential/solid resolution while retaining wall-function
  applicability. This is paired sensitivity, not formal grid independence.
