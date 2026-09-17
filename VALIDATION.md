# Setup validation — 2026-09-17

## Visual requirements extension

Implemented after the initial setup below. Actual STEP **display tessellation**
and a synthetic CAD fixture were generated; no simulation mesh, CFD or physical
thermal prediction was executed. New persistent demo remains unapproved.

| Check | Result | Evidence under runs/ |
| --- | --- | --- |
| CAD display import tests | 2 passed; through-bore: 1 solid, 7 faces, 2 proposed caps | 20260917T215415-cad-display-tests-950ee0e6 |
| Real CLI import + draft initialization | passed | 20260917T215831-requirements-demo-import-047f68cd |
| Requirements backend / HTTP / handoff integration | 21 passed | 20260917T220246-requirements-integration-verification-9e363bb0 |
| Combined existing + new regression suite | 33 passed | 20260917T220730-requirements-regression-0cfb8deb |
| Chromium UI integration | passed, no page errors | 20260917T220530-requirements-browser-final-8c1cca7f |
| New specialist TOML + VS Code task JSON | parsed | 20260917T220739-requirements-config-3e17fd92 |
| Demo proposals saved | approval remains null; physics blank | 20260917T220618-requirements-demo-proposal-27d5ce1e |

Independent report and browser screenshot:
runs/20260917T214909-requirements-doctor-3fabcc48/review.md and browser-review.png.
Browser screenshot uses clearly labeled synthetic test values; those values are
not a real simulation specification. Fake approvals exist only in temporary tests.

The browser exercised actual WebGL render, ray picking, orbit, role assignment,
cap heat rejection, save/reload, area/load display, explicit confirmation, handoff,
and approval invalidation after edits. Tests bind CAD/model/draft versions, reject
stale updates and altered snapshots, verify physical values in exported handoffs,
and preserve approved receipts during preparation.

Pinned runtime assets: Three.js 0.180.0 and Gmsh Python API 4.14.0 (installed
Gmsh runtime reports 4.14.0-git). Browser testing used Playwright 1.58.0 and
Chromium 145.0.7632.6: Ubuntu 24.04 fallback build on this Ubuntu 26.04 host,
plus an extracted libasound library in /tmp. Initial launch failure for missing
libasound is recorded in 20260917T220032-requirements-browser-1f30633d;
no system packages were changed. An initial HTTP test also encountered sandbox
socket restrictions; subsequent permitted loopback tests passed.

Rerun backend tests (loopback permissions required for HTTP checks):

```bash
python3 tools/workbench.py job --label requirements-tests --input tools/workbench.py --input src/workflow.py --input src/requirements/review.py --input src/requirements/server.py --input src/verification/test_requirements.py --input src/verification/test_workflow.py -- python3 -m unittest discover -s src/verification -p 'test_*.py' -v
```

CAD tests: src/cad/fixtures/test_step_preview.py. Browser test source:
tools/test_review_browser.py; its recorded job lists exact inputs and command.
The test-only environment used PYTHONPATH=/tmp/cooling-browser-tools,
PLAYWRIGHT_BROWSERS_PATH=/tmp/cooling-browser-binaries,
PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64, and
LD_LIBRARY_PATH=/tmp/cooling-browser-libs/extracted/usr/lib/x86_64-linux-gnu.
Those /tmp tools may require recreation after restart; none are viewer runtime
dependencies. VS Code UI task invocation and Windows-host browser access were not
tested. Arbitrary STEP extraction and engineering correctness remain unverified.

## Original framework setup evidence

Executed in the current WSL2 Ubuntu environment with Python 3.14.4. No physical
simulation, CAD generation, thermal calculation, or meshing was performed.

| Check | Result | Evidence under runs/ |
| --- | --- | --- |
| Local discovery | pass | 20260917T213320-setup-doctor-e6b88608 |
| OpenFOAM distribution and help probes | v2412 identified; CHT help succeeded | 20260917T213418-setup-cfd-discovery-4f17632d; 20260917T213428-setup-cfd-version-30b58412 |
| Infrastructure tests | 12 passed | 20260917T213754-setup-verification-fixed-3d2b17ec |
| Local Python smoke | pass | 20260917T213808-setup-smoke-2fd6ce5c |
| Prepare incomplete request | pass; no execution | 20260917T213813-setup-prepare-6fe95acb |
| Snapshot status | pass; hashes match | 20260917T213830-setup-status-42a319d0 |
| Incomplete request check | expected exit 1; 16 missing-input issues | 20260917T213830-setup-incomplete-check-a93553ee |
| Five agent/config TOML and two JSON files | parsed successfully | 20260917T213841-setup-config-parse-6f3d1817 |

All four actual custom specialists were spawned in this manager session and
returned role guides and evidence-backed notes. Model/access settings were retained.
The prepared request is 20260917T213813-setup-intake-57487809; it deliberately
contains unresolved physical inputs and all engineering stages remain not_started.

The 12 infrastructure tests exercise missing/type-invalid input, heat-load
ambiguity, structural-completeness versus engineering-readiness claims, copied
inputs and preservation of sources, tampered/missing snapshots, unique output
directories, path/symlink confinement, process failures, timeout and job locking.
Initial test run 20260917T213720-setup-verification-b44b6102 caught a schema-version
type bug (true/1.0 accepted as integer versions). It was fixed before the passing run.

The incomplete-request job's failed status is expected validation behavior, not
a crashed setup. The solver probe's missing foamVersion command is recorded in
its raw log; solver version evidence comes from help banners/package inventory.
An aggregate discovery-shell exit code is not evidence every probe succeeded.

Independent review: runs/20260917T213320-setup-doctor-e6b88608/review.md.
Rerun tests through the recorder:

```bash
python3 tools/workbench.py job --label infrastructure-tests --input tools/workbench.py --input src/workflow.py --input src/verification/test_workflow.py -- python3 -m unittest discover -s src/verification -p 'test_*.py' -v
```

Not verified: physical CAD geometry, meshing, CHT execution, convergence,
conservation, mesh independence, physical-model validity or experimental
agreement. Python 3.10 compatibility is intended but was not executed here.
