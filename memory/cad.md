# CAD notes

- Setup evidence: `runs/20260917T213320-setup-doctor-e6b88608/console.log`
  reports Python 3.14.4 on Ubuntu WSL2; `/usr/bin/gmsh` is on PATH, while
  `FreeCADCmd` and `freecadcmd` are absent from PATH. Gmsh's version and ability
  to perform CAD operations were not checked; PATH absence does not prove that
  FreeCAD is not installed elsewhere. This evidence applies only to the setup
  shell environment. Verify CAD backend versions and functionality before
  selecting or pinning an adapter.
- Setup reviewed `project.json` schema 1 and `docs/contracts.md`; the CAD module
  remains an unimplemented extension point. `src/cad/README.md` defines intake
  and acceptance requirements, not a tested extraction pipeline. No geometry
  operations or simulations were executed by the CAD specialist during setup.
- Display importer evidence: `runs/20260917T215324-cad-display-import-9bfa8ff3`
  and `runs/20260917T215415-cad-display-tests-950ee0e6` used Gmsh runtime
  4.14.0-git (Ubuntu libgmsh package 4.14.0+ds1-1build4), API 4.14.0 and
  Python 3.14.4. The pinned vendored wrapper is recorded in
  `src/cad/vendor/README.md`; no system installation was performed.
  `src/cad/step_preview.py` now imports STEP and emits per-face display triangles
  in mm, source/adapter/wrapper hashes and a settings-specific import fingerprint.
  This supersedes the earlier no-importer status only for display review;
  fluid-domain extraction and CFD adapters remain unimplemented.
- The synthetic 60 x 40 x 20 mm block with an 8 mm diameter through passage
  imported as one solid, seven CAD faces and two explicitly virtual port disks.
  Tests verified dimensions, disk areas/centers, valid display indices, repeat
  import stability, unchanged input hash and refusal to overwrite inputs/outputs.
  A separate solid-cylinder test verified existing end disks are not offered as
  virtual openings. Circular loops are candidates only: no connectivity, inlet
  direction or suitability for simulation is inferred. No solver or volume mesh
  ran. Evidence applies to these simple fixtures, not arbitrary STEP assemblies.
- Baseline extraction evidence: `runs/20260917T231523-demo-exact-geometry-v3-f90f23c1`
  with Gmsh runtime 4.14.0-git/API 4.14.0 extracts the hash-guarded approved demo
  using direct STEP import with `Geometry.OCCTargetUnit=M`, plus its exact bore
  cylinder and conformal OCC fragmentation. Both closed shells, analytical
  volumes/areas and approved identities pass. `src/cad/prepare_demo_baseline.py`
  intentionally rejects other source hashes; this is not general STEP extraction.
- With this backend/demo, importing in mm then OCC dilating by 0.001 produced
  inaccurate mass properties and failed the conservation assertion (recorded
  failed job `runs/20260917T231333-demo-exact-geometry-1aaff3de`). Direct import
  in metres passes analytical volume checks. Do not reuse the failed v1 outputs.
- Circular display-loop normals are unoriented fitted normals. For this through
  bore both display caps had -x normals, but topology probes show inlet outward
  -x and outlet outward +x. Recompute domain-relative normals for solver use.
- `src/cad/mesh_demo_baseline.py` generated conformal MSH2 tetra meshes in jobs
  `runs/20260917T231531-demo-coarse-mesh-7cf85bf1` (89,708 cells) and
  `runs/20260917T231551-demo-fine-mesh-0d13b7e8` (234,070 cells), using the
  verified v3 geometry. Physical volume names fluid/solid and external boundary
  names inlet/outlet/heated/outerWalls support downstream region splitting.
  Internal interface physical export is omitted by default. These are isotropic
  tetra meshes with 0.5/0.35 mm requested wall-edge sizes, not prism layers;
  achieved wall distances, y+ and OpenFOAM quality remain separate checks.
- Aligned-mesh alternative: `src/cad/mesh_demo_structured.py` generates shared-node
  hexahedral O-grids for this exact straight-bore demo, with no CAD design change.
  Jobs `runs/20260917T232704-demo-structured-coarse-mesh-bd63f33d` and
  `runs/20260917T232713-demo-structured-fine-mesh-bc20ac7d` produced 79,872 and
  262,656 cells. Fluid-wall cell-center distances are 74–95 and 48–62 micrometres;
  controlled circular faceting volume deficits are 0.180% and 0.080%. Analytic
  cross-section connectivity, positive areas, matched interface and total volume
  conservation pass. Maximum cross-section nonorthogonality is 65.4/66.1 degrees;
  OpenFOAM quality and solution adequacy require separate CFD evidence. This
  analytic generator is restricted to the approved source hash and dimensions.
- For wall-function mesh refinement, shrinking the wall-normal spacing can leave
  the log-layer validity range. `mesh_demo_structured.py --fluid-radial 9` permits
  independent wall-normal selection while refining axial/circumferential/solid
  cells. Job `runs/20260917T233057-demo-structured-fine-wall-mesh-1f66be7e`
  generated `geometry/structured/fine-wall.msh` with 241,920 cells and verified
  geometric wall-center distance 64.93–84.32 micrometres. This geometric evidence
  does not establish y+; use the corresponding CFD solution for that check.
