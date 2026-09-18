"""Shared OpenFOAM I/O, process and hashing helpers used by every pipeline stage.

Only two OpenFOAM ASCII readers exist in this repository: this package (used by
CFD, results and the driver) and ``src.verification.independent_reader`` (used
by verification so that a parser defect cannot hide in both places).
"""
