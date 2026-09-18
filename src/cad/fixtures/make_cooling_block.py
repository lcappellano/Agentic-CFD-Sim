#!/usr/bin/env python3
"""Synthetic display-only fixture: 60 x 40 x 20 mm block, diameter 8 mm through bore."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.cad.step_preview import backend


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError("Fixture output already exists; use a new versioned path")
    gmsh = backend()
    gmsh.initialize()
    try:
        gmsh.model.add("synthetic_display_fixture")
        block = gmsh.model.occ.addBox(0, 0, 0, 60, 40, 20)
        passage = gmsh.model.occ.addCylinder(-1, 20, 10, 62, 0, 0, 4)
        gmsh.model.occ.cut([(3, block)], [(3, passage)])
        gmsh.model.occ.synchronize()
        output.parent.mkdir(parents=True, exist_ok=True)
        gmsh.write(str(output))
        print("Synthetic display fixture written:", output)
    finally:
        gmsh.finalize()


if __name__ == "__main__":
    main()
