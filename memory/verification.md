# Verification notes

- Two readers exist on purpose: `src/foam/fields.py` (pipeline) and `src/verification/independent_reader.py` (audits). Do not add a third; do not make the audits import the pipeline reader.
- Match the full `value` token, not `valueFraction`, in mixed boundary conditions.
- Low residuals and closed balances do not prove mesh adequacy: the demo tet pair had 22 % pressure-drop sensitivity with converged residuals. A single mesh is `numerically_screened` at best.
- Check colocated local p/T, not port averages: the manifold had thousands of negative-pressure cells behind an acceptable average Δp.
- Numerical energy closure with the cpT liquid model is not physical energy accuracy; the pressure-work scale (Δp·Q) can be percent-level of the applied heat.
- Residual windows must be complete and finite across resumed logs; a missing iteration or a NaN fails the window.
