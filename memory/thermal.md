# Thermal notes

## Setup contract (2026-09-17)

- Origin: `runs/20260917T213320-setup-doctor-e6b88608`; inputs reviewed:
  `AGENTS.md`, `docs/contracts.md`, and `project.json` schema 1.
- Added the request-intake and specialist-handoff guide in
  `src/thermal/README.md`. Applicability: setup and future run planning only.
- Verified from the starter specification: physical inputs remain unresolved;
  default coolant and objective are not evidence of user-supplied conditions.
  Resolve heated boundaries and sourced material properties before any solve.
- Tool version: no thermal calculation tool used or version established by this
  documentation task; consult the setup doctor's recorded inventory for locally
  discovered software. No calculations, CFD, or experimental validation performed.
- Next: after a user supplies a real task, resolve physical inputs, receive a
  verified geometry manifest, and implement/review the first estimate adapter.
  No physical correlation or material-property lesson is verified yet.

## Requirements review contract (2026-09-17)

- Origin: `runs/20260917T214909-requirements-doctor-3fabcc48/plan.md`;
  reviewed current `docs/contracts.md` (project specification schema 2).
- Added `src/requirements/intake-contract.md`: user confirms geometry selection,
  units, directions and physical values before CAD preparation; read-only preview
  inspection is allowed to support that confirmation. Initial scope is steady,
  one solid/coolant, uniform flux or total power, fixed geometry.
- Applicability: requirements handling. Geometry does not identify physical heat
  magnitude or actual flow direction. An open fluid port may lack a solid cap
  face; preserve opening definitions until CAD establishes final fluid boundaries.
- Tool version: documentation-only work; no CAD, thermal or CFD engine invoked.
  No new numerical or material-property results are claimed.
