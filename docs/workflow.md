# Working with the manager

Talk to the main chat. It runs the pipeline and only involves specialists when a
stage fails. You are asked to do exactly one thing yourself: approve the ports,
heated faces and physical values in the browser review.

## Request a new simulation

Put the STEP in `inputs/` and describe the job in plain language, for example:

> Simulate inputs/part.step: copper, water in at 10 °C, 10 MW/m² on the flat
> square face, keep it below 200 °C, 40 L/min, 8 bar absolute at the outlet,
> exterior in vacuum, fixed geometry.

The manager imports the STEP, serves the review, and waits for your approval.
It then writes `specs/<part>.json` and runs `simulate`. You receive
`runs/<run>/report.md` and a viewer link.

## Changing the operating point

Say the new flow, pressure or temperature. The manager edits the spec and reruns
with `--run runs/<run>`; geometry, mesh and materials are reused from cache.

## Reading results

`report.md` states a status:

- `diagnostic`: a numerical or model screen failed; treat numbers as hints only.
- `numerically_screened`: gates pass on one mesh; a finer-mesh comparison is the next step.
- `accepted`: someone recorded an explicit decision.

Nothing is experimentally validated. Mesh sensitivity is a separate run with
`mesh.profile: tet-fine`.

## Resuming a chat

> Read AGENTS.md and memory/manager.md. Run `tools/workbench.py status runs/<run>` and continue.
