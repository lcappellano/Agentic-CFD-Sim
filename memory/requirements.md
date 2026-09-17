# Requirements specialist notes

- 2026-09-17, initial requirements-review implementation: the local review UI uses
  Three.js 0.180.0 and source-import face IDs; bind every selection to the recorded
  import fingerprint. No boundary-role assignment is inferred from cap discovery.
- Initial scope is one material, one coolant, steady operation and uniform heat
  input on fixed geometry. An open passage may have no source CAD cap face;
  purple virtual port caps are explicit proposals for CAD verification.
- CAD cannot supply heat magnitude, actual plumbing direction or operating inputs.
  Only the user may approve the saved, current visual and numerical review. UI
  edits clear confirmation; the server must independently enforce hashes,
  revisions, completeness and approval when producing a CAD handoff.
