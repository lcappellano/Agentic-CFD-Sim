# CFD notes

- 2026-09-17 setup: OpenCFD OpenFOAM v2412 is installed at
  `/usr/lib/openfoam/openfoam2412`; source its `etc/bashrc` before discovery/jobs.
  Package `2412.260127-1`; both CHT solver help banners report build
  `_b8cf4d35-20260127`, patch `260127`. Evidence:
  `runs/20260917T213418-setup-cfd-discovery-4f17632d/console.log` and
  `runs/20260917T213428-setup-cfd-version-30b58412/console.log`.
  Applies to this WSL installation; reconfirm if it changes.
- Initial doctor PATH absence did not mean OpenFOAM was uninstalled.
  `foamVersion` is absent; use the exact executable help banner/package record.
  Installed v2412 tutorials are the starting reference for future adapters.
- Source the OpenFOAM environment before starting the recorder if its parent
  version metadata must be populated. Child-only sourcing left that field null
  in the setup probe; detailed version evidence remains in the console log.
- Setup only: no mesh/solve/postprocessing executed and no CFD adapter exists.
  Next work is an explicitly authorized benchmark with a verified geometry
  manifest and resolved physical inputs, following `src/cfd/README.md`.
