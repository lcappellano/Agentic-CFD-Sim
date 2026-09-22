"""Design-variant booleans on a synthetic notched rib; vane layout arithmetic."""
import math
from pathlib import Path
import tempfile
import unittest

from src.cad.step_preview import backend
from src.cad.variants import build, find_notched_rib_ends, vane_layout


def notched_rib_part(path):
    """Block 12 x 3 x 7 mm with two 1 x 2 mm channels (x 0..5) opening into a collector (x 5..8) and a
    header (x 8..12), the rib between them ending in a 45 degree V-notch (apex x = 5, depth 0.5)."""
    gmsh = backend()
    gmsh.initialize()
    gmsh.option.setNumber('General.Terminal', 0)
    gmsh.option.setString('Geometry.OCCTargetUnit', 'MM')
    block = gmsh.model.occ.addBox(-2, 0, -3.5, 14, 3, 7)
    channels = [gmsh.model.occ.addBox(-1, 1, -2.5, 6.5, 1, 2), gmsh.model.occ.addBox(-1, 1, 0.5, 6.5, 1, 2)]
    collector = gmsh.model.occ.addBox(5.5, 1, -2.5, 6.5, 1, 5)
    # V-notch in the rib (z -0.5..0.5): a wedge with apex at x = 5, opening to full height at x = 5.5
    wedge = gmsh.model.occ.addWedge(5, 1, -0.5, 0.5, 1, 1)  # placeholder replaced below
    gmsh.model.occ.remove([(3, wedge)], recursive=True)
    p = [gmsh.model.occ.addPoint(5, 1.5, -0.5), gmsh.model.occ.addPoint(5.5, 1, -0.5), gmsh.model.occ.addPoint(5.5, 2, -0.5)]
    lines = [gmsh.model.occ.addLine(p[0], p[1]), gmsh.model.occ.addLine(p[1], p[2]), gmsh.model.occ.addLine(p[2], p[0])]
    loop = gmsh.model.occ.addCurveLoop(lines)
    face = gmsh.model.occ.addPlaneSurface([loop])
    notch = gmsh.model.occ.extrude([(2, face)], 0, 0, 1)
    notch_volume = [t for d, t in notch if d == 3]
    solid, _ = gmsh.model.occ.cut([(3, block)], [(3, t) for t in channels + [collector] + notch_volume])
    gmsh.model.occ.synchronize()
    gmsh.write(str(path))
    gmsh.finalize()


class VariantTests(unittest.TestCase):
    def test_bullnose_fills_the_notch_and_rounds_the_rib(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'rib.step'
            notched_rib_part(source)
            gmsh = backend()
            gmsh.initialize()
            gmsh.option.setNumber('General.Terminal', 0)
            gmsh.model.occ.importShapes(str(source))
            gmsh.model.occ.synchronize()
            solid = gmsh.model.getEntities(3)[0][1]
            ends = find_notched_rib_ends(gmsh, solid)
            gmsh.finalize()
            self.assertEqual(len(ends), 1, ends)
            x_plane, sign, y_mid, z0, z1, depth = ends[0]
            self.assertAlmostEqual(x_plane, 5.0, places=5)
            self.assertEqual(sign, 1.0)
            self.assertAlmostEqual(y_mid, 1.5, places=5)
            self.assertAlmostEqual(z1 - z0, 1.0, places=5)
            self.assertAlmostEqual(depth, 0.5, places=5)
            target = Path(tmp) / 'rib-bullnose.step'
            report = build(source, target, bullnose=True)
            self.assertTrue(target.is_file() and target.with_suffix('.json').is_file())
            # The 45-degree notch (depth 0.5, rib width 1, height 1) adds 0.25 mm3; the semicircular nose then
            # removes the two corners outside a radius-0.5 half disc: 2 * (1 - pi/4) * 0.5^2 * 1 = 0.1073 mm3.
            expected = 0.25 - 2 * (1 - math.pi / 4) * 0.25
            self.assertAlmostEqual(report['volume_after_mm3'] - report['volume_before_mm3'], expected, places=3)
            gmsh = backend()
            gmsh.initialize()
            gmsh.option.setNumber('General.Terminal', 0)
            gmsh.model.occ.importShapes(str(target))
            gmsh.model.occ.synchronize()
            solid = gmsh.model.getEntities(3)[0][1]
            self.assertEqual(len(gmsh.model.getEntities(3)), 1)
            self.assertTrue(gmsh.model.isInside(3, solid, [5.02, 1.5, 0.0]))    # former notch apex is now solid
            self.assertTrue(gmsh.model.isInside(3, solid, [5.45, 1.5, 0.0]))    # nose reaches the old prong tips
            self.assertFalse(gmsh.model.isInside(3, solid, [5.45, 1.5, 0.45]))  # but its corners are rounded off
            self.assertFalse(gmsh.model.isInside(3, solid, [5.6, 1.5, 0.0]))    # collector stays fluid
            self.assertEqual(find_notched_rib_ends(gmsh, solid), [])
            gmsh.finalize()
            with self.assertRaises(ValueError):
                build(source, target, bullnose=True)  # never overwrite

    def test_vane_layout_divides_inlet_and_collector_equally(self):
        w_in, w_out = 5.35, 22.97
        rows = vane_layout(w_in, w_out, x_start=57, x_end=31, per_side=2)
        self.assertEqual(len(rows), 4)
        inlet = sorted(z for (x, z), _ in rows if z > 0)
        outlet = sorted(z for _, (x, z) in rows if z > 0)
        self.assertAlmostEqual(inlet[0], w_in / 5)
        self.assertAlmostEqual(inlet[1], 3 * w_in / 5)
        self.assertAlmostEqual(outlet[0], w_out / 5)
        self.assertAlmostEqual(outlet[1], 3 * w_out / 5)
        self.assertEqual({z < 0 for (_, z), _ in rows}, {True, False})


if __name__ == '__main__':
    unittest.main()
