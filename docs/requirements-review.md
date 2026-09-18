# STEP requirements review

The requirements specialist sits between the manager's initial intake and CAD
preparation. Give the manager a STEP path and describe the intended cooling and
heating in ordinary language. The manager delegates to this specialist, which
opens a local interactive review, proposes boundary assignments, and identifies
missing physical inputs. You inspect and correct the model before CAD handoff.

## What you see

- A rotatable, zoomable 3D part with clickable CAD faces and a keyboard surface list.
- **Blue inlet**, **green outlet**, and **orange heated solid surfaces**, with text
  labels. Inspect mode changes no assignments. Choose a role and click to assign;
  assigning another role replaces the previous one on that surface.
- **Purple candidate caps** over supported circular openings. These are visual
  proposals for fluid boundaries, not solid faces or changes to your source CAD.
  Transparent-solid and isolated-surface views help inspect hidden selections.
- Bounding dimensions in millimetres, selected area, heat flux or total power,
  temperatures, materials, flow and outlet absolute-pressure bounds, other thermal
  boundaries, and the objective. Heat enters the orange faces. The temperature
  limit applies to the maximum on those selected heated surfaces.

CAD cannot tell us the actual inlet direction, coolant, heating magnitude or
operating conditions. The agent uses your instructions and labels proposals for
you to confirm. Circular holes can be blind or unrelated to coolant; their actual
connectivity is a later CAD check. Spatial flow arrows are not inferred from the
arbitrary normal orientation of a fitted circle. The direction legend is explicit:
blue inlet → coolant passage → green outlet.

## Your review and handoff

1. Check the part and displayed dimensions. Rotate it and inspect the highlights.
2. Correct assignments and values if necessary; fill missing requirements or tell
   the manager what is unknown. The UI uses K, kg/s, bar and W or W/m².
   Select absolute or gauge pressure. Gauge input needs an explicit ambient
   reference in bar absolute; zero gauge is valid. The displayed conversion and
   saved source/reference distinguish gauge readings from solver absolute pressure.
   Canonical pressure values remain in Pa internally (1 bar = 100,000 Pa).
   Missing, zero-absolute and reversed bounds have distinct inline diagnostics.
3. **Save draft.** Drafts survive reloading; saving edits invalidates an earlier
   approval. Conflicting edits from another tab require reloading the saved draft.
4. When satisfied, enter your reviewer name, tick the explicit confirmation and
   click **Approve this review**. The agent never clicks this for a real user case.
5. Click **Create CAD handoff**, or tell the manager to continue from your approved
   review. The manager verifies the receipt and passes the package to CAD.

Only complete, current, explicitly approved requirements can be handed off.
Source STEP, imported display, selected boundaries and numerical values are
bound to hashes and a revision. A changed CAD/import needs a new review; altered
snapshot files block approval/handoff. An approval confirms your intended setup,
not geometry validity or a verified simulation.

The handoff copies the STEP, display model, requirements and approval, exports a
project.json, and records exact boundary identities and virtual-cap definitions.
CAD then validates the part, extracts solid/fluid regions and maps approved
selections onto actual fluid boundaries. Thermal, CFD and verification follow
the baseline-first workflow. No solver starts from the viewer.

## Local commands

```bash
.venv/bin/python tools/workbench.py review-import --step inputs/part.step --label part
.venv/bin/python tools/workbench.py review-serve runs/<review>            # http://127.0.0.1:8765
.venv/bin/python tools/workbench.py review-status runs/<review>
.venv/bin/python tools/workbench.py review-handoff runs/<review>          # after your approval
.venv/bin/python tools/workbench.py review-verify runs/<review>/handoffs/revision-<n>-<id>
```

The handoff directory is the `handoff` value of a simulation spec (`docs/pipeline.md`).
