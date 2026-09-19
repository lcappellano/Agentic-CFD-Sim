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
Flow and return pressure are optional in the review: leave them blank if you do
not know them, enter equal values to fix them, or a range to constrain the
estimate. The manager then runs a correlation prescreen: a table of flows and
outlet pressures with estimated pressure drop, wall and heated-face temperature
brackets, and an estimated operating point (the smallest flow that keeps the
heated face within 75 % of the allowed rise, and a return pressure that keeps
the wall subcooled). Blank values are filled from that estimate and CFD starts;
the report states the values and the reasoning. If the estimate needs an
implausible velocity, outlet pressure or pressure drop, exceeds a bound you
gave, or beats the pump limit, nothing is capped: the manager stops, shows you
the table and the estimate with the reasons, and you decide (run it as it is,
change the design, or raise the plausibility thresholds). If you would rather
choose the point yourself every time, say so: the manager stops after the
prescreen, shows you the table, and records your choice in the spec. You receive `runs/<run>/report.md`
and a viewer link.

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
