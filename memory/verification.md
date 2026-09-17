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
