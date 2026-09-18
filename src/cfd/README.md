# src/cfd

OpenCFD v2412 `chtMultiRegionSimpleFoam` two-region cases, driven by `src/pipeline`.

| module | role |
| --- | --- |
| `settings.py` | derive complete case settings from operating point + geometry manifest + material basis + numerics profile |
| `cht_case.py` | write the case (dictionaries, fields, mesh conversion); binds mesh/basis/settings hashes in `manifest.json` |
| `transport.py`, `turbulence.py` | thermophysical dictionaries (constant or polynomial μ/k), RANS/wall-function choices |
| `run_case.py` | checkMesh, decomposition, solver run, reconstruction; write interval aligned to chunk ends |
| `run_bounded.py` | chunked execution with numerical, transport-range and phase gates → `bounded-review.json` |
| `summarize_case.py` | balances, port totals, hottest face, y+, transport range → `summary.json` |
| `initialize_velocity.py`, `warm_start.py`, `numerical_variant.py` | potential-flow U start, internal-T seeding on an identical mesh, relaxation change on a checkpoint |
| `operating_search.py` | flow bracketing from verified points (agent-driven, never automatic) |

Numerics live in `src/pipeline/profiles/numerics.json`; see `docs/pipeline.md`.
Case files: `settings.json`, `basis.json`, `geometry-manifest.json`, `acceptance-criteria.json`,
`manifest.json`, `bounded-review.json`, `summary.json`, `audits/`. Fields are ASCII.
