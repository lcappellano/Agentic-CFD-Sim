# Verification workflow

The verification specialist reports to the manager and owns this directory,
`memory/verification.md`, and the review report assigned for each run. It reads
the original request, versioned specification, manifests, and raw evidence.
It requests repairs from the responsible specialist rather than editing that
specialist's implementation during review.

Every review uses **pass**, **fail**, or **not checked** for each applicable
check, links evidence, and states the limits of the conclusion. Missing evidence
is never a pass. Distinguish successful command execution, numerical verification,
and experimental validation; none implies the next.

## Setup and intake review

- Confirm the request snapshot and input hashes identify the reviewed versions.
- Check units, unresolved inputs, fixed-geometry authorization, and stage ordering.
- Check that preparation creates records without executing engineering stages.
- Inspect command logs, exit codes, timeout policy, and job serialization.
- Treat discovered executable paths as discovery, not proof of solver usability.

## Engineering review after implementation

| Check | Required evidence |
| --- | --- |
| Geometry identity | Source and exported region hashes, units, transforms, versions |
| Boundary identity | Heated faces and area, inlet/outlet, walls, paired interfaces |
| Geometry validity | Connectivity, watertightness, region volumes, documented checks |
| Settings identity | Geometry-manifest hash, exact case settings and solver version |
| Heat input | Applied boundary/source data and integrated total power |
| Mass balance | Signed boundary mass flows and stated normalization/tolerance |
| Energy balance | Heat input/removal, other losses/storage, normalization/tolerance |
| Convergence | Residual histories and stability of reported engineering outputs |
| Mesh sensitivity | Comparable refined-mesh results and estimated output sensitivity |
| Physical model | Material/property sources, pressure convention, flow and phase applicability |
| Acceptance | Temperature/pressure/flow objective evaluated over the recorded bounds |

Thresholds belong in the case plan before acceptance; there is no universal
tolerance that establishes validity. A single mesh cannot establish mesh
independence. A feasible point does not establish a minimum-flow or minimum-power
optimum. No result outside the explored bounds is implied.

For setup-only work, all engineering checks remain **not checked**. The current
project has no implemented CHT evidence checker or physically validated case.

## Infrastructure regression checks

`test_workflow.py` checks intake constraints, copied-input integrity, source
preservation, no execution/readiness claims, and recorder failures/timeouts/locks.
It uses temporary directories and text fixtures, not engineering geometry.

```bash
python3 tools/workbench.py job --label infrastructure-check --input tools/workbench.py --input src/workflow.py --input src/verification/test_workflow.py --timeout 30 -- python3 src/verification/test_workflow.py
```
