"""Focused checks of actual STEP display import, not a thermal/CFD test."""
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.cad.step_preview import backend, preview_step
from src.foam.hashing import digest

FIXTURE = Path(__file__).with_name("cooling_block_through_bore_v1.step")


class PreviewTests(unittest.TestCase):
    def test_through_passage_faces_and_virtual_disks(self):
        before = digest(FIXTURE)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "preview.json"
            result = preview_step(FIXTURE, output)
            self.assertEqual(result, json.loads(output.read_text()))
            self.assertEqual(digest(FIXTURE), before)
            self.assertEqual(result["source"]["sha256"], before)
            self.assertEqual(result["units"], "mm")
            self.assertEqual(result["scope"], "display_only")
            self.assertEqual(result["solid_count"], 1)
            self.assertEqual(len(result["faces"]), 7)
            self.assertEqual(len(result["virtual_faces"]), 2)
            for actual, expected in zip(result["bounds"], [0, 0, 0, 60, 40, 20]):
                self.assertAlmostEqual(actual, expected, places=5)
            ports = sorted(result["virtual_faces"], key=lambda p: p["centroid_mm"][0])
            for port, x in zip(ports, [0, 60]):
                self.assertEqual(port["kind"], "virtual_port")
                self.assertTrue(port["candidate"])
                self.assertAlmostEqual(port["radius_mm"], 4, places=6)
                self.assertAlmostEqual(port["area_mm2"], 16*math.pi, places=6)
                for actual, expected in zip(port["centroid_mm"], [x, 20, 10]):
                    self.assertAlmostEqual(actual, expected, places=6)
                self.assertAlmostEqual(abs(port["normal"][0]), 1, places=6)
            for face in result["faces"] + ports:
                self.assertGreater(face["area_mm2"], 0)
                self.assertEqual(len(face["positions"]) % 3, 0)
                self.assertEqual(len(face["triangles"]) % 3, 0)
                self.assertGreater(len(face["triangles"]), 0)
                self.assertTrue(all(0 <= i < len(face["positions"])/3 for i in face["triangles"]))
            repeat = preview_step(FIXTURE, Path(directory) / "repeat.json")
            self.assertEqual(result["import_fingerprint"], repeat["import_fingerprint"])
            self.assertEqual(result["faces"], repeat["faces"])
            with self.assertRaises(ValueError):
                preview_step(FIXTURE, output)
            with self.assertRaises(ValueError):
                preview_step(FIXTURE, FIXTURE)

    def test_existing_circular_faces_are_not_virtual_openings(self):
        with tempfile.TemporaryDirectory() as directory:
            cylinder = Path(directory) / "solid_cylinder.step"
            gmsh = backend()
            gmsh.initialize()
            try:
                gmsh.model.add("existing_disks")
                gmsh.model.occ.addCylinder(0, 0, 0, 10, 0, 0, 4)
                gmsh.model.occ.synchronize()
                gmsh.write(str(cylinder))
            finally:
                gmsh.finalize()
            result = preview_step(cylinder, Path(directory) / "cylinder.json")
            self.assertEqual(len(result["faces"]), 3)
            self.assertEqual(result["virtual_faces"], [])


if __name__ == "__main__":
    unittest.main()


class SquareChannelTests(unittest.TestCase):
    def test_square_through_channel_gives_two_polygon_caps(self):
        gmsh = backend()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "bar.step"
            gmsh.initialize()
            try:
                gmsh.model.add("square_bar")
                bar = gmsh.model.occ.addBox(-1.5, -1.5, -15, 3, 3, 30)
                channel = gmsh.model.occ.addBox(-.5, -.5, -16, 1, 1, 32)
                gmsh.model.occ.cut([(3, bar)], [(3, channel)])
                gmsh.model.occ.synchronize()
                gmsh.write(str(source))
            finally:
                gmsh.finalize()
            result = preview_step(source, Path(tmp) / "bar.json")
            self.assertEqual(len(result["faces"]), 10)
            ports = sorted(result["virtual_faces"], key=lambda p: p["centroid_mm"][2])
            self.assertEqual(len(ports), 2)
            for port, z in zip(ports, (-15, 15)):
                self.assertEqual(port["shape"], "polygon")
                self.assertNotIn("radius_mm", port)
                self.assertAlmostEqual(port["area_mm2"], 1.0, places=9)
                self.assertAlmostEqual(port["centroid_mm"][2], z, places=6)
                self.assertAlmostEqual(abs(port["normal"][2]), 1, places=6)
                self.assertGreater(len(port["triangles"]), 0)
