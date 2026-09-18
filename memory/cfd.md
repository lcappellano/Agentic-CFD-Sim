# CFD notes (OpenCFD v2412; each bullet is encoded in a profile or module, listed for the why)

- `gmshToFoam` then `splitMeshRegions -cellZones -overwrite` needs root `fvSchemes`/`fvSolution` present; solid external patches must become `wall` for `wallHeatFlux`; solid needs a `p` field with heSolidThermo. (`cht_case.py`)
- Solid `h` uses PCG/DIC; multi-region parallel needs per-region `decomposeParDict`. (`cht_case.py`, `run_case.py`)
- With g = 0, `p` and `p_rgh` are absolute static pressure in Pa.
- Water Pr ≈ 6 with wall functions: use `compressible::alphatJayatillekeWallFunction`, not plain alphatWallFunction. (`turbulence.py`)
- Aligned hex meshes: full corrected solid Laplacian, `leastSquares` gradient, 3 non-orthogonal passes (profile `hex-kepsilon`). Isotropic tets showed 22 % pressure-drop mesh sensitivity on the demo; hex O-grids removed it.
- Tetrahedral passages with sharp ribs: `leastSquares` + full correction diverged at iteration 3; `cellLimited Gauss linear 1` with 2 passes was stable (profile `tet-robust`).
- SST needs `wallDist { method meshWave; }` in fluid fvSchemes. Spalding nut + blended omega wall functions are tutorial-supported in v2412.
- A uniform initial U on a refined manifold made the first energy solve go negative; `potentialFoam -region fluid -initialiseUBCs` (U only, no phi/p) fixed the startup. (`initialize_velocity.py`, profile `tet-robust`)
- Enthalpy relaxation 0.3 in both regions made thermal transport crawl (600 iterations, 3 W pickup of 27 kW); switching to 0.9 via `numerical_variant` advanced it. 0.9 from the start was stable with potential-flow U. Profile `tet-robust-slow-energy` exists for startups that diverge at 0.9.
- Fields are only saved at write times: chunk ends must land on a write; `run_case` adjusts `writeInterval` with a gcd.
- The polynomial transport (`icoPolynomial`/`hPolynomial`) has no range clamp in the solver; the audits reject out-of-range temperatures. Fit 278.15–440 K covered inlet undershoots that a 283.15 lower bound did not.
- Never source the OpenFOAM bashrc after `set -e` in a shell; it exits. The pipeline sources it in Python instead.
