# Thermal and hydraulic workflow

The thermal specialist owns `src/thermal/`. It supports the manager with energy
balances, estimates, operating-case selection, and interpretation. This directory
is currently a documented extension point: no engineering adapter or simulation
has been implemented or executed as part of workflow setup.

## Request intake

The user can describe a new run in ordinary language and attach or identify CAD.
The manager translates the request into a versioned run specification, resolves
missing physical facts, and records assumptions. Unknowns remain explicit; the
starter `project.json` is not a completed simulation request.

| Input | Required physical facts or user constraints | Manager preparation |
| --- | --- | --- |
| Geometry and heat location | CAD/version and units; which components or surfaces receive heat | Have CAD specialist map descriptions to stable boundary identities and verified heated areas |
| Heat input | Total power in W, heat flux in W/m², or volumetric heating in W/m³; spatial distribution; load duration/profile when transient | Represent each source explicitly; integrate over verified area/volume to establish total applied W; reconcile redundant power/flux inputs |
| Solid and interfaces | Material grades; known coatings, joints, gaps, or thermal contact resistance | Select sourced conductivity and, when needed, density and heat capacity, with units, applicable temperature range, and documented interface assumptions |
| Coolant and inlet | Fluid/composition and inlet temperature; known flow or hardware flow limits | Select sourced fluid properties and temperature/pressure dependence; resolve the unfilled coolant field explicitly |
| Thermal surroundings | Known ambient temperature, insulation, external convection/radiation, prescribed temperatures or additional heat losses | Document each remaining boundary and its model; resolve physically material unknowns before a solve |
| Pressure and flow | Known outlet absolute pressure, available pressure range, mass/volume flow limits, and hardware restrictions | Record mass-flow bounds in kg/s and outlet absolute-pressure bounds in Pa separately; convert volume flow using stated density; document exploratory bounds if no hardware limits are available |
| Objective and acceptance | Feasibility or quantity to minimize; temperature limit and where it applies; other performance limits | Define explicit acceptance tolerances, search bounds, and a stopping criterion in the run plan |
| Geometry permission | Whether geometry changes are authorized and which dimensions/features may change | Search operating conditions on fixed geometry first; record a reason and permitted bounds for any later design iteration |

Use explicit units on every supplied quantity. Gauge pressure requires a stated
reference to obtain absolute pressure. A limit at a sensor or component is not
automatically the same as a maximum heated-wall temperature limit. The user need
not supply property tables or solver settings: the manager and specialists select
and document defensible models, sources, numerical controls, and tolerances.

For a steady run, establish a time-independent load and boundary state. A transient
run additionally needs initial temperatures, time-dependent inputs, and a duration.
If a physical input cannot be established, return the unresolved item to the
manager rather than inventing a value. New specification fields must be integrated
by the manager into shared contracts and validation before they are used.

## Bounded specialist handoff

1. Receive the objective, exact specification and geometry-manifest versions,
   owned output paths, acceptance criteria, and scope from the manager. Read
   `docs/contracts.md` and `memory/thermal.md`.
2. Once a real run is authorized and geometry verified, establish total applied
   heat and a bulk coolant energy balance. Label these as analytical estimates,
   separate from executed CFD and experimental validation.
3. Choose pressure-drop and heat-transfer correlations only after checking their
   flow-regime, geometry, development-length, roughness, property, and phase
   assumptions. Record their validity limits and uncertainty. Do not infer boiling
   margin from a pressure drop alone; absolute pressure and local temperature matter.
4. Propose one baseline and a small set of subsequent cases, stating which
   uncertainty each resolves. Agree with the manager on operating bounds and a
   stopping criterion: accepted verified solution, exhausted stated bounds, or
   insufficient model validity/evidence. Verify the baseline before a sweep.
5. Report target-only pressure drop separately from whole-loop pump requirements.
   A pump recommendation requires losses from the rest of the loop and any pump
   constraints; missing loop information stays explicit.
6. Return inspectable source and a compact report containing assumptions, property
   sources, estimates, case recommendations, validity limits, evidence paths, and
   unresolved items. Store project-specific facts in the run; add only verified
   reusable lessons to role memory with run and tool versions.

Future executable estimates belong in `src/thermal/` and run through
`tools/workbench.py job` with all relevant input files recorded. Case sweeps use
scripts, not a model call for each solver iteration. No estimates, meshing, or
physical solves should be started during setup-only work.
