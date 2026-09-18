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

## Final results viewer — 2026-09-17

- User requested interactive final CFD inspection. CFD exported saved fields, CAD
  built Three.js UI, verification independently checked data and browser behavior.
  Manager integrated read-only loopback server, CLI and documentation.
- Current export: baseline run/results-viewer/v1, canonical fine corrected case
  at iteration 2000. Viewer port 8766; initial requirements port 8765 unchanged.
  Six boundary surfaces and nine cell-intersection slices; T, fluid p and speed.
  Pressure displays bar gauge/absolute with 1.01325 bar reference. No solver rerun.
- Guide docs/results-viewer.md; work record runs/20260917T235215-results-viewer-2423202f.
  Nine data/backend tests and Chromium 145 browser interactions passed. Source and
  payload hashes are checked on serving. Adapter remains canonical-demo-only.
- Installed pip 26.2.1 and optional Playwright 1.58.0 in project .venv for browser
  verification; requirements-dev.txt pins browser Python dependencies. Runtime
  viewer uses standard library and existing vendored Three.js 0.180.0.

- Results navigation follow-up: middle-drag rotates, Ctrl+middle pans, left-click
  probes, scroll zooms, right-drag remains pan. Reversed previous rotation per
  user feedback and disabled inertia. Retains orbit camera (not full SOLIDWORKS
  trackball emulation). Chromium interaction checks passed with no page errors:
  runs/20260918T000551-results-cad-mouse-browser-1b52502a. No simulation changes.

- Navigation correction: user found reversed rotation worse and requested default
  direction. Restored OrbitControls rotateSpeed=1; middle-button mapping and
  immediate stopping retained. No simulation or field changes.

## Navigation redesign — 2026-09-17

- User identified rotation flipping/fighting mouse, not latency. Replaced fixed-up
  OrbitControls with official pinned Three.js r180 ArcballControls; URL/SHA recorded
  in vendor manifest and existing MIT license retained. Initial Orbit setup
  constructed controls before changing camera Y-up to Z-up, a cached-axis mismatch.
- Results viewer now uses orthographic projection, free rotation, middle rotate,
  Ctrl-middle/right pan, wheel zoom, left probe, no inertia. Seven views; F fits
  preserving orientation, Home resets iso. Event-driven rendering avoids idle GPU
  work. Service restarted on port8766 for the new vendor route.
- Navigation tests now check quaternion continuity, top/bottom out-and-back,
  unchanged pan orientation, repeatable presets, fit and resize. Do not judge
  navigation correctness merely by changed screenshots. No CFD rerun or changes.

Navigation redesign verified: 9 backend/data tests passed in
`runs/20260918T001548-arcball-server-verification-3c302ece`; Chromium navigation
and field checks passed in `runs/20260918T002017-results-arcball-verified-dbd77aaf`.
Top/bottom reversible rotation, bounded orientation increments, seven presets,
pan, no inertia, Fit/Home and resize passed. Initial Home PNG equality failure
was isolated to 759 legend-text pixels differing by 1/255; every camera state
value exactly matched. Home-only pixel tolerance documented in browser test.
Source hashes and whitespace checks pass. Viewer running on port8766; user
manual feel remains the final usability check, not proof of SOLIDWORKS parity.

## First real manifold intake — 2026-09-17

- Active review runs/20260918T002459-astra-manifold-review-27f127f8, port8767.
  Source Cooling_Test_Part_Astra_Generated_Manifold.STEP preserved, SHA256
  c042996a9a2b362f519f7c8d07129d84e717d378b8251321fadf17c2605dc813.
  Import job runs/20260918T002459-astra-manifold-import-15d91933 succeeded.
- CAD intake:1solid226faces,156×10.6×52mm. Four cap candidates are concentric
  pairs: true opening proposals Ø8 port:22-583 (+x),port:16-584 (-x); Ø10 outer
  tube loops overlap solid and are not valid fluid caps. Connectivity unverified.
- User specifies copper/water,10MW/m² on ONE square flat face,200°C heatedmax,
  10°C inlet. Saved draftrev1 SI:1e7W/m²,473.15K,283.15K. Square faces221/226
  each2704mm² ->27.04kW for one full face. No face assignment or approval yet.
  Await flow/pressure bounds,other thermal BC,objective,heated-face and inlet choice.
- Requirements viewer now shares proven Arcball orthographic interaction style
  with results. Synthetic approval/form browser test passed in
  runs/20260918T002718-manifold-intake-browser-7423481a; never approved real case.
- No extraction, computational meshing or solve. Demo adapter cannot run this
  manifold unchanged. Next: user visually selects/approves exact requirements,
  then geometry-specific fluid extraction and physical/model applicability review.

- User follow-up saved as draftrevision2: maximum50L/min,8bar (meaning pending),
  seek minimum required pressure to about10% and corresponding flow,heated<200°C.
  Vacuum exterior,no convection;radiation choice pending. Do not use8bar as
  outlet absolute pressure without clarification. Volumetric flow cap retained in
  objective/notes pending density conversion; canonical mass bounds left unset.
  Proposed conditional bracket/refinement strategy in search-plan.md.
- Actual manifold browser check passed without modifying review:
  runs/20260918T002756-manifold-real-viewer-5a051172. Screenshot manifold-review.png
  shows revision1 conditions (before operating-limit follow-up); reload viewer
  for latest draft. Requirements are still unapproved, no simulation executed.

## Pump/return pressure clarification

User confirms atmospheric tank return and8bar maximum pump PRESSURE RISE.
Saved into current draftrevision5 preserving user's selected surfaces. Explicit
standard atmosphere assumption101325Pa absolute fixed outlet; neglected return
line/elevation losses. Optional max_pump_pressure_rise_Pa=800000 is separate
from outlet bounds. UI now distinguishes these and offers atmospheric shortcut.
Do not interpret8bar as outlet absolute pressure or claim whole-loop pump sizing.
35 requirements tests pass: runs/20260918T003517-pump-pressure-regression-7a83f35d.
Current user-selected inlet port:9-585 is incorrect outerØ10 cap; informed user
to replace with co-centered innerØ8 port:22-583 before approval. Outlet
port:16-584 and heatedface:221 preserved. Radiation and flowbounds unresolved.

## Authorized manifold run

Active runs/20260918T003814-manifold-baseline-128470d0. User authorizes simulation/search with reusable software. Reviewrev6 approvedsource/selections verified; archived handoff immutable. Explicit chat fixes1–50kg/s to1–50L/min and confirms neglect radiation. Overrides separately recorded;resolved-project authoritative with density conversion pending. CAD/CFD/verification specialists active; existing CFD specialist supplies thermal basis due thread limit. Manager serializes recorded compute jobs.

## Manifold diagnostic review — 2026-09-18

Run 20260918T003814-manifold-baseline-128470d0: geometry extracted/checked, 577944 tetrahedra, OpenCFD v2412 patch260127. Two 1000-iteration diagnostics (50 and15 L/min) independently rejected: energy errors12.32/36.59%, thermal drift, negative local absolute pressure at50 and wetted saturation screen failures at15. No accepted200°C result or minimum pressure; not proof of infeasibility. See run report/report.md and verification.md. Explicit1–50L/min and adiabatic vacuum corrections resolved; original approved receipt immutable.

Reusable extraction, case/runner/warm-start/search support and independent audits now in src/. Sixteen combined source tests pass in 010841-manifold-transport-source-tests-44e555a0. CoolProp7.2.0/numpy2.5.3 pinned project-venv dependencies for reusable polynomial transport fit; optional native transport source not solver-validated. Candidate283.15–440K range too narrow for slight inlet undershoots; refit with lower margin before use. Cp/rho remain constant. Pending user decision: allow controlled downstream back-pressure before atmospheric tank? Do not change outlet until answered. Requires revised transport/wall treatment, converged balances and mesh comparison before searching. No current solver running; diagnostic artifact review complete.

Continuation2026-09-18: native polynomial transport startup10iterations passed (job160404), independently coefficient-bound by verifier (160459). It still fails physical/numerical criteria, as expected for startup. Fitv2 lower bound278.15K; reusable property-pressure sample shows max~0.48%mu/.107%k and11%rho/3.72%cp overfullstable-liquidgrid; qualifyachievedT. Refined central-boxmesh2,857,014tetra generated101s (job160614), samegeometrymanifest; fiveconfigtests pass.17channelbins atx0 recorded for actualmeshsection flow integration. CFD preparing optionalSST/Spalding revised15L/min atmospheric case and bounded continuation. Userbackpressure question remains unanswered; do notinfer approval from continue.

## Manifold continuation stopping point — 2026-09-18

Run20260918T003814-manifold-baseline-128470d0 now awaiting operating/model decision; no solver running. Authoritative report/report.md and verification/energy09-210-review.md. FixedCAD retained. Refined15L/min SST/polynomial case v3 stabilized with reusable potentialvelocity initializer;600 iterations still99.99%energydeficit dueenergyrelaxationlag. Full-state freshvariant refined-15lpm-energy09-v1 uses bothh relaxation0.9;210 iterations stopped persistent wallphasefailure. Heated151.53°C is NOT accepted:26.07%energydeficit,16.44K/100drift,all8residualgroupsfail,107363wetfacesaboveequilibriumTsat. Bulk/fit pass only forunconvergedstate. No minimum pressure or proof of infeasibility.

Independentchecks nowread resumedlogs andSSTomega withfinite/fullwindow guards. Numericalvariant4tests, pumpbudget2tests andsearchcontract11tests pass. Pumpsearchrequires keyword pump_pressure_rise_Pa; atmosphericstationaryreservoir idealizedmetricptin−101325includesoutletjet loss (diagnostic0.50635bar vscomponent0.37518). Actualexternallosses omittedexplicitly. Pendinguserquestion allowscontrolledreturnbackpressure? Noanswer/nooutletchange;current101325Pa. Preservefrozenresolved-project/caseprovenance; version anynewphysicalspec. Finer.75sizemeshconfig preparednotrun (6–8Mestcells,RAMneedsreview). Next: resolvephysicalpath, valid/convergedcandidate, matchedmesh/wall/property review, thenpumpsearch. Do notrerunoldfailedstartups/regeneratecasecode.

## Fixed40 single-case completion — 2026-09-18

User cancelled pressure/flow search to reduce credits; explicitly fixed 40 L/min and 8 bar absolute outlet, comparing calculated component pressure difference against 6 bar. Run 20260918T003814-manifold-baseline-128470d0, case fixed-40lpm-8barabs-v1, OpenFOAM v2412 patch260127, iteration2000. Heated111.57 °C, outlet19.67 °C, static component drop2.443 bar. Thermal/energy/phase screens pass; pressure drift/residual criteria fail. Diagnostic, no compliance/mesh independence claim. All compute stopped; do not resume sweep. Whole-loop suction/reference unspecified. Reused CFD pipeline; new results/saved_case.py exports stopped tetrahedral cases with frozen provenance and honest acceptance, extending existing viewer. Viewer port8768/export fixed40-v1; report/fixed40-report.md is current.

Viewer fixed40 browser check passed, server8768 left running. Local browser checks require PLAYWRIGHT_BROWSERS_PATH=/tmp/cooling-browser-binaries and LD_LIBRARY_PATH=/tmp/cooling-browser-libs/extracted/usr/lib/x86_64-linux-gnu (existing Chromium1208 environment). Eleven results tests passed.
