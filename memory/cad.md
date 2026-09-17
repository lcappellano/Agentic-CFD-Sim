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
