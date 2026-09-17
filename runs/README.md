Local job directories contain job.json and console.log. The manager adds geometry,
cases, results, and verification reports in explicitly assigned run directories.
Large run artifacts are excluded from Git. Keep durable backups for important runs.

Prepared requests contain project.json, workflow.json, plan.md, and a copied CAD
file when available. They are distinct from execution job directories. The manager
links later jobs in workflow.json and updates stage state with evidence. Use
`python3 tools/workbench.py status runs/<request-directory>` to check snapshot
integrity. Preparation and successful jobs do not establish simulation validity.
