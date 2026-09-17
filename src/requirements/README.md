# Requirements specialist

Start with ../../docs/requirements-review.md for user interaction, commands and limits.
intake-contract.md defines physical intake. review.py owns revisioned drafts,
approval validation and CAD packages; server.py serves the local web/ UI. CAD
display import is provided by ../cad/step_preview.py. Only a user's explicit review
may approve a real case; automated tests use temporary synthetic fixtures.

The manager can propose values and selected faces via review-draft; it cannot
infer unknown heat magnitude, actual coolant direction or user's approval from CAD.
Fields omitted from a user request remain visibly unresolved. Preserve source CAD
and use the exact approved hash/fingerprint-bound package for downstream handoff.

No solver, simulation mesh, or automatic arbitrary STEP region extraction runs here.
