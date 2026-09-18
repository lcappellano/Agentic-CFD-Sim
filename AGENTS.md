# Cooling agent workbench

The main conversation is the manager. Specialists (`requirements`, `cad`,
`cfd`, `thermal`, `verification`) are spawned only when a pipeline stage fails
or a decision needs discipline judgment. Read this file, `docs/pipeline.md`,
and `memory/manager.md` at session start; nothing else is required.

## Running a part

1. Put the STEP in `inputs/`. `tools/workbench.py review-import --step ...`,
   serve the viewer, and let the **user** select ports and heated faces and
   approve. Never approve for the user. `review-handoff` writes the package.
2. Write a spec in `specs/<part>.json` (see `docs/pipeline.md`; ten lines is typical).
3. `tools/workbench.py simulate specs/<part>.json`, then `status runs/<run>`.
4. Read `state.json`/`report.md`. Act on the stop reason. Do not read solver
   logs unless a stage failed; the stage log is `runs/<run>/logs/<stage>.log`.

## Rules

- Change the spec, a profile in `src/pipeline/profiles/`, or a module in `src/`.
  Never write scripts inside `runs/` and never edit generated case files by hand.
- A recurring fix belongs in code: add or adjust a profile, extend a material,
  widen a check. Add a test next to it. `tools/workbench.py test` must pass.
- One compute job per machine; the driver holds the lock. Do not poll a
  running solve with the model; wait for the driver to return.
- Report `state.case.status` verbatim: `diagnostic`, `numerically_screened`,
  or `accepted`. Only a human writes `accepted` (a `decision.json` in the run).
- Keep memory files short: one bullet per reusable lesson with the run that
  produced it. Project narrative goes in the run's `report.md`.
- Use `.venv/bin/python`. Never `sudo pip` or global installs. Pin new
  dependencies in `requirements-*.txt`.
- Do not overwrite input CAD; do not change geometry unless the user allows it.

## Manager workflow when something fails

| stage failed | first look | who |
| --- | --- | --- |
| handoff | approval missing or edited after approval | requirements + user |
| geometry | `logs/geometry.log`: usually port selection (wrong loop) or unsupported topology | cad |
| mesh | Gmsh error; try `tet-coarse` or a refinement box | cad |
| case / solve | `stop_reason` in state; try `tet-robust-slow-energy`, then `numerical_variant` | cfd |
| audit | which check failed, in `cases/*/audits/*.json` | verification |
