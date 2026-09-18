# Cooling Agent Workbench

A VS Code / WSL starter project for an interactive Codex manager and five
specialists, with CAD and simulation computation on your computer.

**Fixed-demo baseline completed and independently reviewed (2026-09-17).**
The approved copper/water demo was solved locally with OpenCFD OpenFOAM v2412.
At 0.50148 L/s and 0.1 bar gauge outlet pressure, the predicted heated maximum is
308.252 K against a 500 K limit. Conservation, convergence and paired-mesh checks
pass with documented model limits. See [the baseline guide](docs/baseline-demo.md),
[local result report](runs/20260917T231138-demo-baseline-7716aa5b/report/report.md),
and [manager workflow](docs/workflow.md). Raw run artifacts are ignored by Git.

**Visual requirements review added:** the new requirements specialist imports
STEP into a local 3D viewer, proposes inlet/outlet/heated surfaces, collects physical
values and waits for your explicit visual confirmation before CAD handoff. See
[the requirements viewer guide](docs/requirements-review.md) for the demo and usage.

## What works now

- Project-scoped Codex specialist definitions: requirements, CAD, CFD/CHT, thermal/hydraulic
  analysis, and verification. The main chat is the manager.
- Manager instructions, separate source ownership, persistent notes, and handoff
  contracts. Current Codex supplies actual agent spawning and conversation state.
- Standard-library Python tool discovery and local process execution with logs,
  input hashes, recorded exit status, timeout, and one-job-at-a-time locking.
- VS Code tasks and a smoke test. No API key or Python package is required for
  the infrastructure commands.
- `check`, `prepare`, and `status` commands for missing-input reporting, copied
  request/CAD snapshots, stage ownership, and snapshot integrity checks.
- STEP surface display, 3D face selection, candidate circular port caps, saved
  requirements drafts, user approval and checked/versioned CAD handoff packages.

- Exact solid/fluid preparation for the guarded through-bore demo, conformal
  aligned meshes, recorded local MPI CHT solves, independent numerical review,
  and plots from saved fields.

**Not implemented yet:** arbitrary STEP-to-CHT automation, general passage
extraction/healing, geometry optimization, operating-point search, or an unattended
manager service. The verified adapters support this fixed demo; a new geometry
requires preparation and review. See VALIDATION.md for evidence and limits.

## 1. Open it locally in VS Code

On Windows, install VS Code and Microsoft's WSL extension. Use WSL2 Ubuntu for
the Linux engineering tools. Check WSL distributions in Windows PowerShell:

```powershell
wsl --list --verbose
```

Open Ubuntu. Put the extracted cooling-agent-workbench folder under your Linux
home, for example ~/projects/cooling-agent-workbench. The files can be moved
through Windows Explorer using the WSL filesystem, or copied from Downloads in
Ubuntu. Keeping the working cases on the Linux filesystem avoids heavy cross-
filesystem I/O when meshing and solving. WSL is on your computer, not a cloud VM.

Inside Ubuntu, open the project:

```bash
cd ~/projects/cooling-agent-workbench
code .
```

VS Code should show WSL: Ubuntu in its lower-left connection indicator. In its
terminal, pwd should show a Linux path under /home/ rather than /mnt/c/.
Install Python 3.10+ and Git in Ubuntu if missing:

```bash
sudo apt update
sudo apt install python3 python3-venv git
```

These commands run on your PC only when you execute them. This ZIP installs
nothing automatically.

## 2. Enable the manager and specialists

Install the official OpenAI Codex extension in VS Code and open its sidebar.
Sign in with your ChatGPT account if your plan provides Codex access. Select local
work, and verify it can see this WSL folder and run Linux commands there.
Use the Codex CLI inside WSL as an alternative if the IDE cannot use your Linux
tool environment. Follow the official WSL instructions linked below.

Use a current Codex release. It loads custom specialist TOML files from
.codex/agents/. Each has name, description, and developer_instructions; model
and permission settings are inherited. .codex/config.toml limits active workers
to four. If project trust is requested, inspect these files and trust this project
to allow its configuration to load. Restart the chat after config changes.

AGENTS.md assigns the main conversation the manager role and explicitly requests
specialist delegation. No separate manager application or API subscription is
needed for this interactive setup. These files customize Codex; they do not
implement a standalone language-model runtime.

**Cost:** local solver execution uses your CPU/RAM. Hosted AI still uses your
account allowance or credits. Signing in with an API key instead uses API billing.
Local execution does not make manager/worker model calls free. Supported plans
and limits can change; check the pricing link below and your account.

## 3. Check the starter

In the WSL terminal:

```bash
python3 tools/workbench.py doctor
python3 tools/workbench.py job --label smoke --input examples/smoke.py -- python3 examples/smoke.py
git init
git add .
git status
```

The smoke test produces a new runs/<timestamp>-smoke-<id>/ directory containing
job.json and console.log. It is not a physical calculation. In VS Code,
Terminal > Run Task offers equivalent discovery and smoke tasks.

Missing OpenFOAM commands in doctor output are expected if OpenFOAM is absent or
its environment has not been sourced. Have the CFD specialist inspect your exact
Ubuntu and OpenFOAM versions before installing/configuring a compatible stack.
CAD tools such as FreeCAD and solver dependencies are installed separately.

## 4. Start talking to the manager

Paste this into the local Codex chat:

> Read AGENTS.md and act as this project's manager. Use the project-defined cad,
> cfd, thermal, and verification subagents for bounded tasks. First inspect the
> local environment and run the infrastructure smoke test. Then implement the
> next requested simulation using the verified fixed-demo baseline as a reference.
> Read docs/baseline-demo.md and the latest manager notes before selecting adapters.
> Keep scripts in each specialist's src directory and run records under runs/.
> Delegate independent work and serialize dependent steps. Report actual tool
> outputs and clearly identify any missing capabilities. Keep me informed of the
> files changed and how to inspect or rerun each stage.

For a new part, put your STEP in inputs/ and give the manager
the file path, heat flux, heated surfaces, material, temperature limit, coolant
inlet temperature, flow/pressure bounds, and whether geometry changes are allowed.
It should fill project.json and adapt the baseline workflow to that geometry.
For a new chat, say: "Read AGENTS.md and memory/manager.md; resume this project."

## What to inspect

| Location | Purpose |
| --- | --- |
| AGENTS.md | Main manager instructions and project rules |
| .codex/agents/ | Five editable specialist definitions (four concurrent workers) |
| src/requirements/ | Local 3D review UI, requirements and approved CAD handoff |
| src/cad/ | Geometry-processing code |
| src/cfd/ | Meshing, solver setup, and postprocessing code |
| src/thermal/ | Analytical estimates and search strategy code |
| src/verification/ | Evidence checks and review code |
| memory/ | Compact, version-aware lessons and project decisions |
| project.json | Current engineering requirements |
| docs/contracts.md | Data expected at each handoff |
| tools/workbench.py | Local process recorder |
| runs/ | Logs, command records, generated cases, and results |

Git's Source Control view shows each file change. The main manager integrates
shared changes; worker ownership prevents accidental simultaneous edits. These
ownership rules are instructions, not security boundaries.

## Local job runner

The manager can record any trusted local command, with an explicit working
directory, timeout, and input files. For example:

```bash
python3 tools/workbench.py job --label example --timeout 60 --input examples/smoke.py -- python3 examples/smoke.py
```

For an implemented OpenFOAM case, pass its directory with --cwd, repeat --input
for relevant settings/geometry manifests, then put the solver command after --.
Source the actual installed OpenFOAM environment first. The runner uses direct
argument execution, not an implicit shell. It does not sandbox child programs.
Keep credentials out of command arguments because commands are logged.

The timeout defaults to one hour; choose a suitable explicit limit for long jobs.
Only one recorded job runs at a time. Parallel agent reasoning can continue while
the job runs; simulation concurrency is a separate resource decision. Review RAM
and CPU needs before extending this to multiple simultaneous solves.

The runner waits in the foreground. Keep its terminal and WSL running. For long
unattended work, add a durable job service or terminal session manager. An abrupt
shutdown can leave status='running' in an interrupted job record; reconcile it
against actual processes and outputs before restarting. Jobs are not retried
automatically. A job with status='succeeded' still requires numerical checks.

## Build toward the full framework

1. Preserve and replay the verified fixed-demo CHT baseline and its evidence.
2. Implement STEP inspection, domain extraction, and robust boundary labeling.
3. Add fixed-geometry operating sweeps with scripts, explicit bounds and caching.
4. Add conservation, convergence, mesh sensitivity, and model-validity checks.
5. Add permitted geometry optimization, preserving each geometry/run association.
6. Add durable scheduling and manager resumption only when unattended workflows
   are needed. Pin validated tool versions and archive evidence-backed examples.

Prefer reusable scripts and case templates over generating everything anew for
each part. During a long solve, avoid frequent agent polling; return concise
completion summaries and selected diagnostics. This reduces model usage.

## Official setup references

Configuration checked against documentation on 2026-09-17; client formats can evolve.

- [Codex IDE extension](https://learn.chatgpt.com/docs/codex/ide)
- [Codex custom subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Codex in WSL](https://learn.chatgpt.com/docs/windows/wsl)
- [VS Code WSL workflow](https://code.visualstudio.com/docs/remote/wsl)
- [Codex pricing and usage](https://learn.chatgpt.com/docs/pricing)

## Final simulation viewer

Inspect the accepted demo in the [3D results viewer](docs/results-viewer.md):
rotate and probe temperature, pressure in bar and fluid speed, with transparent
solid surfaces and internal slices. Launch with `tools/workbench.py results-serve`
or the VS Code results-viewer task. Saved fields and review provenance are checked;
viewing does not launch a simulation.
