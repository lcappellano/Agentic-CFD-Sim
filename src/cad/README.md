# src/cad

| module | role |
| --- | --- |
| `step_preview.py` | STEP display tessellation in mm, face IDs and circular port-loop candidates for the browser review |
| `extract_passage.py` | approved handoff → `solid.brep`, `fluid.brep`, conformal `coupled.brep/.geo`, `manifest.json` (SI; ports at any orientation) |
| `mesh_regions.py` | conformal MSH2 tets with interface-distance sizing and optional refinement boxes; sizes from `src/pipeline/profiles/mesh.json` |
| `vendor/gmsh.py` | pinned Gmsh 4.14.0 API wrapper (system `libgmsh` runtime) |
| `fixtures/` | synthetic through-bore block used by tests |

Supported: one solid, one connected passage closed by user-selected planar
circular openings. Unsupported: assemblies, multiple circuits, non-circular
ports, healing. The extractor raises rather than guessing.
