"""Exercise local execution without pretending to run a simulation."""
import json
import platform
import sys

print(json.dumps({
    "kind": "infrastructure_smoke_test",
    "python": sys.version.split()[0],
    "platform": platform.platform(),
    "message": "Local Python executed successfully. No CAD or CFD calculation performed."
}, indent=2))
