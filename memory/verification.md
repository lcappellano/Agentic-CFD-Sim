# Verification notes

- Setup review: runs/20260917T213320-setup-doctor-e6b88608/review.md, 2026-09-17.
  Python 3.14.4 infrastructure tests: 12 pass in
  runs/20260917T213754-setup-verification-fixed-3d2b17ec. Scope is intake, snapshots,
  recorder behavior and no-execution claims only; no numerical/physical validation.
- Python Boolean values compare equal to integers. Schema version validation must
  reject true and 1.0 explicitly; the original failure and repaired implementation
  are recorded in the setup review and protected by test_workflow.py.
- Compound shell discovery success is not success of every subcommand. OpenFOAM
  help banners confirmed v2412 patch 260127 despite unavailable foamVersion in
  runs/20260917T213428-setup-cfd-version-30b58412. Applies to tool discovery only;
  neither help output nor installed-package records establish solver correctness.
- Future reviews must inspect raw fields/logs and use pass/fail/not checked for
  hashes, units, heated faces/heat load, balances, convergence, mesh sensitivity
  and physical-model applicability. Missing engineering evidence stays not checked.
- Visual requirements workflow: originating run
  runs/20260917T214909-requirements-doctor-3fabcc48; Python 3.14.4 tests in
  runs/20260917T220246-requirements-integration-verification-9e363bb0 pass 21
  backend/HTTP/integration checks. Scope: explicit confirmation, snapshot and
  revision binding, stale-write rejection, boundary consistency and preserved
  CAD handoff, not geometry validity or physical simulation. Fake approvals were
  confined to temporary synthetic fixtures. HTTP tests need permitted loopback.
  Browser evidence in runs/20260917T220530-requirements-browser-final-8c1cca7f
  (Chromium 145.0.7632.6) confirms WebGL picking/orbit and confirmation/edit flow;
  reviewed screenshot and test source. Persistent demo remained unapproved.
- Handoff manifests must cross-check boundary mapping, identity and exported
  physical settings against the approved draft, not merely hash the exported
  files. This review found the missing semantic comparison; regressions now cover
  it. Current exported absolute paths pin executable handoffs to their original
  location; archived copies remain evidence and are checked by workflow status.
- Pressure form repair: originating run
  runs/20260917T224853-pressure-form-doctor-1ddb713b. Python 3.14.4 regression
  evidence runs/20260917T225343-pressure-gauge-verification-40ab4f73: 33 tests pass,
  including 12 added pressure cases. Distinguish missing endpoints, zero absolute,
  reversed bounds and finite-positive fixed bounds; incomplete drafts may save
  without becoming approvable. Gauge zero is valid only with an explicit positive
  reference and positive converted absolute pressure; raw values/reference and
  canonical bounds survive saved/handoff snapshots. Conversion mismatch cannot
  approve. Legacy drafts without pressure_input retain absolute semantics.
  This tests intake behavior only, not pressure/phase suitability for a solve.
  Verification used temporary fixtures and made no changes to the live review.
- Baseline development, runs/20260917T231138-demo-baseline-7716aa5b,
  OpenCFD v2412 patch260127/Python3.14.4: low residuals and conservation did
  not ensure mesh accuracy. Initial tetra pair showed ~22% pressure-drop
  sensitivity; retained as rejected development evidence. Aligned extruded
  meshes remove obvious pressure extrema, but require their own paired review.
- Same run/version: solid nonorthogonal diffusion limiter changed heated Tmax
  by 0.636 K and moved the hotspot from top center to lateral edge in an aligned
  coarse mesh. Review numerical schemes as well as mesh counts; do not infer
  a temperature-location parser bug from an unexpected pattern alone. Static
  face-coordinate matching established the pattern existed in the raw field.
- Same run/version: modeled steady energy accounting requires signed enthalpy
  plus kinetic flux and fixed-temperature inlet diffusion. Corrected aligned
  coarse case had −0.132598 W heat into fluid at inlet; including it closed the
  240 W modeled balance to 2.61e−8 fraction. Exact inlet-gradient reconstruction
  applies only to orthogonal straight extrusions, not arbitrary hexahedra.
- Independent ASCII audit must match the complete `value` token, not the prefix
  of `valueFraction`; mixed temperature conditions contain both. Initial audit
  diagnostic was repaired before final accepted evidence. Reference values and
  gradient coefficients must never substitute for saved boundary temperatures.
- Final corrected aligned pair in same baseline run, OpenCFD v2412 patch260127,
  independent job20260917T234047-baseline-independent-final-pair-d875925b:
  adopted numerical checks passed; heated maximum308.25175K, mesh difference
  0.00410K/0.04968% of rise, pressure-drop sensitivity0.62524%. Final report
  verification.md accepts limited baseline screening, not experimental validation.
  Fine yPlus29.405–50.483 included8/6912faces below nominal30 at first axial row;
  qualified manual wall-model acceptance documented separately from automated
  numerical checks. A nominal guideline is not silently promoted to a new hard
  criterion or silently relaxed to produce a pass. Preserve explicit judgment.
