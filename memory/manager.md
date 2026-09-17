# Manager notes

- Setup run: runs/20260917T213320-setup-doctor-e6b88608 (2026-09-17).
  User requested workflow setup and an explicit stop before any simulation.
  No CAD generation, meshing, estimates, or physical solver execution in this task.
- All four actual specialized subagents (cad, cfd, thermal, verification) were
  spawned using project roles. Their definitions already existed and were retained;
  model and permission settings remain inherited. Manager owns shared files.
- WSL2 Ubuntu, Python 3.14.4; OpenCFD OpenFOAM v2412 package 2412.260127-1 found.
  Source /usr/lib/openfoam/openfoam2412/etc/bashrc before recorded engineering jobs.
  See memory/cfd.md for help-only probe evidence. Gmsh/ParaView on PATH; FreeCAD
  commands absent from PATH. CAD backend/solver case functionality unverified.
- Added src/workflow.py and CLI check/prepare/status: structural intake, unique
  run snapshots with hashes, unresolved inputs and owned stages. These do not
  run engineering calculations. JSON stage status is manager-maintained, not
  scheduling logic. The generic job recorder is not an execution authorization gate.
- project.json schema 2 remains an unfilled request; coolant and objective are
  now null to avoid treating starter defaults as user-supplied physics. No real
  simulation specification has been supplied. No automatic STEP-to-CHT adapter.
- User entrypoint and copyable request template: docs/workflow.md. On a new chat,
  read AGENTS.md, these notes and the selected run plan; inspect evidence before
  resuming. Start fresh specialist sessions as needed, using role memory.
- Next engineering work, when requested: resolve benchmark inputs, verify a CAD
  backend, implement/run/review one reproducible CHT benchmark, then adapt the
  verified path to user CAD. Do not start this from setup alone.
- Setup checks: 12 tests passed in runs/20260917T213754-setup-verification-fixed-3d2b17ec;
  smoke and prepare/status CLI passed. check correctly reports 16 unresolved inputs
  in the empty project. VALIDATION.md indexes logs and independent review. Prepared
  setup request: runs/20260917T213813-setup-intake-57487809 (no engineering execution).

## Requirements specialist and viewer — 2026-09-17

- New user request adds visual requirements confirmation BEFORE CAD handoff.
  Built .codex/agents/requirements.toml and ran an actual requirements specialist
  with its instructions loaded. Existing max four concurrent workers retained;
  there are now five disciplines, with requirements upstream of CAD.
- Main evidence run: runs/20260917T214909-requirements-doctor-3fabcc48; plan.md and
  independent review.md. Browser source/usage: docs/requirements-review.md.
- Stack: Three.js 0.180.0 vendored locally; Gmsh wrapper 4.14.0 with installed
  4.14.0-git OpenCASCADE runtime. CAD display adapter in src/cad/step_preview.py.
  Per-face display tessellation and candidate circular planar opening caps work
  on fixture (1 solid, 7 faces, 2 cap proposals). No fluid extraction or solver.
- New src/requirements review backend/UI provides proposals, physical intake,
  explicit user confirmation, hash/revision-bound handoff, invalidation after
  edits, and verified receipt archiving via prepare. Agents must never approve a
  real review for the user. test approvals used temporary synthetic data only.
- Persistent demo: runs/20260917T215831-requirements-demo-634b5abf. Illustrative
  inlet/outlet/top-heat highlights saved, approval null and physical values blank.
  Serve with python3 tools/workbench.py review-serve <that directory> (port 8765).
  Service must remain running; no unattended agent scheduler was installed.
- Verification: 33 combined regression tests passed in
  runs/20260917T220730-requirements-regression-0cfb8deb; 2 CAD import tests passed
  in runs/20260917T215415-cad-display-tests-950ee0e6. Chromium 145 browser test
  passed in runs/20260917T220530-requirements-browser-final-8c1cca7f.
- Initial limits: single solid/material, steady, uniform heating, fixed geometry;
  temperature limit on selected heated surfaces. Planar circular virtual caps
  are proposals only, with topology/connectivity unverified. Handoff reuse pins
  absolute original paths; archival copies preserve evidence but need an explicit
  migration feature before relocation/reuse. Full simulation remains unimplemented.
- Next: user supplies STEP path and physical intent; requirements creates a new
  review, proposes selections, resolves missing values and awaits user's visual
  approval. Only then CAD preparation and eventually the verified CHT benchmark.

## Pressure form repair — 2026-09-17

- Run: runs/20260917T224853-pressure-form-doctor-1ddb713b. User reported repeated
  pressure error despite saving. Values saved correctly; original lower bound
  0 was interpreted as absolute while user intended gauge. Generic schema-name
  error was misleading. Added precise inline missing/zero/reversed diagnostics.
- User explicitly confirmed gauge pressure and reference 101325 Pa, then asked
  for pressure units in bar. UI now displays bar with mode selector and explicit
  ambient reference (1.01325 bar for this case); canonical solver values stay Pa.
  Optional pressure_input metadata preserves original reference and values;
  conversion consistency is required for approval. Zero gauge is supported.
- Preserved user's latest saved range [10000,60005] Pa as [0.1,0.60005] bar gauge;
  did not restore the earlier zero. Revision 6 backed up then updated to revision 7
  with approved interpretation/reference, not review approval. Source, selections
  and other physical values unchanged. Recorded in
  runs/20260917T225730-pressure-reference-update-ea571e1a.
- 45 regression tests passed: runs/20260917T225642-pressure-bar-regression-8a44f5d6.
  Actual Chromium save/reload/gauge/bar/approval guards passed:
  runs/20260917T225646-pressure-bar-browser-df89a5ab. Viewer restarted on port 8765.

## First authorized baseline — 2026-09-17

- User explicitly authorized running approved demo baseline with fixed geometry. Active run: runs/20260917T231138-demo-baseline-7716aa5b; revision 8 receipt verified and immutable copies prepared. Latest approved outlet bounds are 0.1–4 bar gauge, superseding earlier memory values. Copper/water, 300 K inlet, 100 kW/m² heating, 500 K heated-face limit, 0.5–10 kg/s.
- Actual CAD, CFD, thermal, verification specialists assigned; manager owns run plan/workflow and integration. Read current plan/status before resuming. No geometry optimization authorized.
- Created .venv with --without-pip (system ensurepip unavailable); use .venv/bin/python. No external Python dependency installed.

## Baseline completed and accepted — 2026-09-17

- Run runs/20260917T231138-demo-baseline-7716aa5b is complete; authoritative result
  report/report.md and verification-decision.json: accepted_with_model_limits.
  Canonical case-hex-coarse-corrected / case-hex-fine-corrected, 2000iterations,
  4localMPI ranks, OpenCFD v2412 patch260127; fixed STEP hash unchanged.
- At0.5kg/s(0.501481L/s), outlet0.1barg(1.11325bara),240W: heatedTmax308.251748K
  vs500K;wetTmax304.96104K;conservative saturationmargin70.8218K;Δp0.0869754bar.
  Paired mesh ΔT0.00410K,Δp0.625%; conservation/residual/drift criteria pass.
- Final geometry/v3; meshes geometry/structured/coarse and fine-wall,79872/241920
  hex cells. Tetra diagnostics failed22%Δp sensitivity. Limited solid diffusion
  biased temperature; full correction/leastSquares/3nonorthpasses adopted.
- Fine yPlusmin29.405:8faces,0.07685%wetarea,firstinletrow below nominal30.
  Independent explicit wall-model qualification accepted; automatedflag retained.
  No experimentalvalidation, boiling simulation, geometrychange or operating sweep.
- 47 regressiontests pass; finalplots viaParaView6.0.1 bundledmatplotlib3.10.7,
  avoiding new pipdependencies. Job index and failed development evidence retained.
- All full fields/logs remain local under ignored runs/. Existing public repo
  publication predates these changes; no new commit or push performed in this task.
- Next requested engineering task: use verified demo as reference, visuallyapprove
  any new STEP requirements and implement/review its geometry-specific adapter.
  Do not assume demo-only source guards support arbitrary parts.
