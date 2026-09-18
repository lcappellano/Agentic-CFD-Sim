# Requirements review before CAD preparation

This contract describes the initial supported request: one solid region, one
coolant, steady operation, one inlet set and one outlet set, and uniform heating
specified either as heat flux or total power over the selected heated surfaces.
Geometry stays fixed. Multiple materials, transient loads, nonuniform heating,
multiple independently controlled ports, and geometry optimization require an
explicit scope extension. This document defines intake, not an implemented solver.

Read-only CAD inspection and preview generation may occur during intake so the
user can identify boundaries. The confirmed request is handed to CAD for region
preparation only after the visual and numerical review below. Do not confuse this
inspection with approval to repair, redesign, mesh, or solve the geometry.

## Minimum review panel

| UI field | Required content before CAD handoff |
| --- | --- |
| CAD and scale | Source filename/version and hash; coordinate units; representative displayed dimensions with units, confirmed against the intended part |
| Solid | Material grade or an explicitly supplied material-property definition; the selected solid region |
| Coolant | Fluid identity and composition; inlet temperature with units |
| Inlet and outlet | Clearly labeled visual boundary sets and the direction legend “blue inlet → passage → green outlet”; user confirmation that this matches the physical plumbing |
| Heating | Selected solid surfaces; exactly one positive heating input: uniform heat flux in W/m² or total power in W distributed uniformly across their combined area; explicit “heat into solid” label |
| Other thermal boundaries | Explicit condition for surfaces not heated or coupled to coolant; e.g. a user-confirmed adiabatic idealization, or ambient and heat-transfer data for an external-loss model |
| Operating point or search bounds | A fixed positive mass flow or a lower/upper mass-flow range in kg/s; pressure entered in bar as absolute or gauge with explicit ambient reference. Canonical outlet absolute-pressure bounds are stored in Pa |
| Goal | Requested result or search objective; initial workflow fixes temperature compliance to the maximum on the selected heated surfaces, explicitly displayed with units |
| Geometry permission | Fixed geometry for this initial scope; any proposed change requires a separate request/scope extension |

Values may originate from the user's supplied task or from a manager proposal,
but proposals are visibly labeled until confirmed. The manager converts the user's
request to the viewer's labeled SI fields and retains original units in notes/task
records; the initial UI is not a free-form unit converter. Gauge pressure must include
its atmospheric/reference pressure before conversion. A volumetric flow input
requires a stated conversion density; it must not be silently relabeled kg/s.

CAD geometry alone cannot establish heat-flux magnitude, heat-flow direction,
actual coolant-flow direction, fluid composition, or operating pressure. Port
size and location can support a proposal but cannot establish which port is the
inlet. Similarly, a large flat surface is only a candidate heated surface.

For total power, show “uniform distribution over the combined selected heated
area.” Once area is available, show the derived flux alongside the unchanged
entered power. For a flux input, show the derived total power once area is
available. These are derived values, not a second independent heat specification.
No areas or derived values are invented while geometry is unresolved.

## Boundary identification and open ports

Bind selections to the exact CAD version and preview geometry, using stable
boundary IDs and visible labels. Provide enough views or interactive rotation to
inspect hidden and ambiguous surfaces. Color must be accompanied by text labels.

A solid containing an open fluid passage often has no solid face across its port.
Do not require the user to select a nonexistent inlet/outlet cap face or label the
surrounding annular solid face as the fluid inlet. Let the user identify the opening
or its rim loop and review a proposed planar cap with position, orientation, units,
and explicit inlet/outlet role. Spatial arrows are not inferred from arbitrary
fitted normal orientation. Record this as a proposed fluid boundary to be constructed during
CAD preparation. The CAD specialist verifies closure, connectivity, cap geometry,
and the final mapping to fluid-region boundary IDs before solver handoff. Ambiguous
or nonplanar openings require resolution; they are not silently capped.

## Confirmation and downstream choices

The user confirms both the displayed geometry selections and numerical values.
The review record must identify the source/preview/specification hashes, units,
boundary selections or proposed port definitions, heating type/value/direction,
flow direction, and all remaining physical inputs in the panel. Store an explicit
confirmation action and time. Do not mark approval based on a successful file
upload, automatic boundary guesses, or elapsed time. Any change to confirmed
geometry, selections, or physical values invalidates the applicable confirmation
and must be shown again. Routine solver settings do not need repeated user review.

The manager then selects sourced material properties and applicable ranges,
property dependence, fluid/phase and turbulence models, correlations for estimates,
mesh controls, numerical schemes, convergence and conservation tolerances, and
mesh-sensitivity checks with the specialists. These engineering choices are
documented and reviewed before a solve; they are not mandatory user-entry fields.
Physical interface/thermal assumptions that materially change the requested
problem must be disclosed as proposals, not hidden among numerical settings.
Record a search stopping criterion before execution: a verified acceptable point,
exhausted documented bounds, or insufficient model validity/evidence.

## Recommended semantic keys

The manager owns the executable schema and validation; these are semantic
requirements to map into it, not an independently implemented schema:

- Source CAD path/hash, preview hash, geometry units and displayed dimensions.
- Solid material, coolant composition, inlet temperature, operating mode.
- Inlet/outlet/heat selection IDs, port-opening definitions where needed, and
  explicit coolant and heat direction conventions.
- Exactly one uniform heat-flux or total-power input; other thermal boundaries.
- Mass-flow value/bounds, outlet absolute-pressure value/bounds, objective,
  temperature limit and location, and fixed-geometry scope.
- Review state, confirmed specification hash, confirmation time, and unresolved
  items. Missing fields remain unresolved; no physical defaults count as approval.

Target pressure drop remains distinct from whole-loop pumping requirements.
The latter needs loop-loss information beyond the CAD component. A component-only
request must not be represented as establishing pump suitability.

Optional `max_pump_pressure_rise_Pa` records a positive pump differential-pressure
ceiling independently of outlet absolute pressure. It displays in bar and survives
CAD handoff. Legacy reviews may omit it; null means unspecified. The atmospheric
return shortcut explicitly sets both outlet bounds to101325Pa absolute without
changing the pump ceiling. Applying that pressure at a part outlet assumes
negligible return-line losses and elevation; component pressure drop alone does
not establish the pump requirement for a full cooling loop.
