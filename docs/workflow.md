# Working with the manager

Talk to the main chat. The manager maintains the request, delegates bounded work,
coordinates dependencies, and integrates the specialist review into one report.
You do not need to open specialist chats or manually dispatch their commands.
The original four roles and the new requirements specialist have run in this project; their
configuration matches the [official subagent schema](https://learn.chatgpt.com/docs/agent-configuration/subagents).
Model and access settings remain inherited.

| Role | Responsibility |
| --- | --- |
| manager | Intake, assumptions, plan, shared tools, job coordination, final report |
| requirements | Interactive STEP preview, proposed boundaries and physical inputs, explicit user review before CAD handoff |
| cad | Solid/fluid regions, geometry integrity, named boundaries and interfaces |
| thermal | Heat and hydraulic estimates, physical applicability, bounded operating cases |
| cfd | Mesh, CHT setup, local solver execution and postprocessing |
| verification | Independent review of raw evidence, balances, convergence and mesh sensitivity |

## Request a new simulation

Place the CAD file in inputs/ and describe the request in ordinary language.
Supply what you know; the manager identifies missing facts and records modeling
choices. Users may give familiar units; the manager converts to the SI units in
project.json. Never substitute an example specification for the actual request.

Useful request template (brackets are deliberately unfilled):

> Start a new cooling simulation for inputs/[part].step. CAD units are [units].
> The solid is [material]; the coolant is [fluid/composition]. Apply [total W
> or W/m²] to [identified faces]. Inlet and outlet are [faces/ports]. Coolant
> enters at [temperature]; keep [surface] below [temperature]. Explore flow
> [range with units] and outlet absolute pressure [range with units]. Other
> surfaces are [insulated/ambient/convection/etc.]. My objective is [feasibility,
> lowest flow, or lowest pumping power]. Geometry changes are [allowed/not allowed,
> with limits]. Use [steady/transient] conditions. [Any runtime/resource limits].

The current preparation helper supports steady requests and one positive uniform
heat flux or total heat input. Transient, mixed loads, multiple solids/materials,
or nonuniform sources need an explicit schema and adapter extension first.
Material properties, sources, tolerances, interface assumptions and phase-model
applicability are resolved with the specialists before physical execution.

## Sequence after a simulation request

1. Manager checks the toolchain and input requirements, records assumptions, and
   creates a unique run directory with copied inputs, hashes, ownership and plan.
2. Requirements opens the [3D review](requirements-review.md), highlights proposed
   ports and heated surfaces, and collects your explicit confirmation of the
   current displayed geometry and values. CAD then establishes verified regions
   and boundaries from the approved handoff. Thermal establishes estimates
   and a baseline operating point; independent preparation can proceed concurrently.
3. CFD builds one baseline case. Heavy executable work runs one job at a time
   through the recorder, with explicit inputs and a timeout.
4. Verification reviews geometry, boundary conditions, conservation, convergence,
   mesh sensitivity and physical-model validity. Failed checks trigger repairs.
5. A scripted operating sweep follows a reviewed baseline when requested. Fixed
   geometry is the default. Design changes require authorization in the request.
6. Manager delivers settings, commands, logs, temperature/pressure/flow results,
   review evidence and unresolved limits. A successful process exit is not proof
   of a converged or physically validated result.

The first engineering milestone remains a simple reproducible benchmark before
adapting arbitrary STEP files. Geometry extraction and solver adapters are not
implemented yet. Setup completion does not imply the simulation pipeline works.

## Infrastructure commands

These helpers require only Python's standard library and launch no engineering tool:

```bash
python3 tools/workbench.py doctor
python3 tools/workbench.py check
python3 tools/workbench.py prepare --label my-part
python3 tools/workbench.py status runs/<run-directory>
```

`check` exits 1 for incomplete/invalid intake and 0 for structurally complete
intake. Property/source and acceptance objects still require semantic review;
`simulation_ready` stays false. `prepare` intentionally accepts incomplete input,
preserves a byte-for-byte specification snapshot, copies available CAD, and lists
unresolved inputs in plan.md. It exits 0 when preparation succeeds. It does not
grant execution permission. `status` checks copied-input hashes and exits 1 if
they changed. Snapshots are preserved by convention, not OS write protection.
Original source paths are workspace-relative; downstream work uses the run copies
listed in workflow.json. Make a new preparation for revised inputs.

For an auditable preparation, the manager records the helper itself:

```bash
python3 tools/workbench.py job --label prepare --input project.json --input src/workflow.py --input tools/workbench.py -- python3 tools/workbench.py prepare --label my-part
```

This creates a job record and a separate request directory named in its console
log. Future stage job paths go in workflow.json `jobs`; the manager updates stage
states and plan.md. This is an interactive workflow, not an unattended scheduler.

## Local environment and resuming

Setup discovered WSL2 Ubuntu, Python 3.14.4 and installed OpenCFD OpenFOAM v2412
(package 2412.260127-1). CHT help commands work after loading its environment:

```bash
source /usr/lib/openfoam/openfoam2412/etc/bashrc
python3 tools/workbench.py doctor
```

Source before invoking the recorder so job.json captures the OpenFOAM version.
No mesh or solver case has been executed. Gmsh and ParaView were found on PATH;
CAD backend functionality remains unverified. See memory/cfd.md for evidence.

Ask for progress or change constraints in this manager chat. For a new chat say:

> Read AGENTS.md and memory/manager.md. Resume runs/[run-directory]/plan.md;
> inspect recorded status and evidence before continuing.

Role definitions and notes persist on disk; the manager starts specialist sessions
when needed. Keep the client and local environment running during jobs. There is
no background manager service, automatic retry, or automatic resumption. Full logs
and fields stay under runs/; inputs/ and runs/ are excluded from Git by the starter
ignore rules, so retain/back them up separately when needed.
