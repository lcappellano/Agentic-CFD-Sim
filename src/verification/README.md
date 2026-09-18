# src/verification

Independent checks; every result is pass, fail or not checked.

| module | role |
| --- | --- |
| `independent_reader.py` | the second OpenFOAM ASCII reader (never import `src.foam.fields` here) |
| `audit_geometry.py` | re-import BREPs, volumes, closed shells, interface, approved identities, cap orientation |
| `audit_fields.py` | balances, phase and transport screens, heat input, y+, pressure budget from raw fields |
| `review_history.py` | monitor stability and residual windows across resumed logs |
| `channel_flows.py` | branch flow integration on tetrahedral plane cuts (diagnostic) |
| `test_*.py` | regression tests, including intake/recorder/requirements guards |

The driver runs `audit_geometry`, `audit_fields` and `review_history` automatically.
A human records acceptance in `decision.json`; code never does.
