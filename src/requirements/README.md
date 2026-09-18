# src/requirements

Browser review where the user selects inlet/outlet openings and heated faces
and confirms physical inputs. `review.py` holds drafts, approval and handoff
(hash-bound); `server.py` is the loopback HTTP service; `web/` the Three.js UI.
Commands: `tools/workbench.py review-import | review-serve | review-draft | review-handoff | review-verify`.
See `docs/requirements-review.md`.
