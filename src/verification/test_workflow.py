"""Infrastructure checks only; all fixture records live in temporary directories."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("workbench_under_test", ROOT / "tools/workbench.py")
workbench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workbench)
import workflow


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "inputs").mkdir()
        self.cad = self.root / "inputs/fixture.step"
        self.cad.write_bytes(b"fixture only, not an engineering STEP file\n")
        self.spec = {
            "schema_version": 2, "cad_file": "inputs/fixture.step",
            "heated_faces": ["heater"], "inlet_faces": ["inlet"],
            "outlet_faces": ["outlet"], "heat_flux_W_m2": 100,
            "total_heat_load_W": None, "maximum_surface_temperature_K": 350,
            "inlet_temperature_K": 300, "solid_material": "fixture solid",
            "coolant_material": "fixture coolant", "objective": "fixture feasibility",
            "other_thermal_boundaries": "fixture insulated", "operating_mode": "steady",
            "mass_flow_bounds_kg_s": [0.01, 0.02],
            "outlet_absolute_pressure_bounds_Pa": [100000, 200000],
            "geometry_changes_allowed": False, "assumptions": [],
            "material_properties": {"fixture": "unverified"},
            "acceptance_criteria": {"fixture": "unverified"},
        }

    def prepare(self):
        source = self.root / "project.json"
        source.write_text(json.dumps(self.spec, indent=2))
        before = source.read_bytes(), self.cad.read_bytes()
        # A preparation step must never delegate work to an external process.
        with patch("subprocess.Popen", side_effect=AssertionError("Unexpected execution")):
            result = workflow.prepare(self.root, "project.json", "fixture")
        self.assertEqual(before, (source.read_bytes(), self.cad.read_bytes()))
        return result

    def test_empty_intake_reports_missing_inputs_without_readiness(self):
        result = workflow.check_spec(self.root, {})
        self.assertFalse(result["intake_complete"])
        self.assertFalse(result["simulation_ready"])
        for field in ("cad_file", "heated_faces", "material_properties", "mass_flow_bounds_kg_s"):
            self.assertTrue(any(field in issue for issue in result["issues"]), field)

    def test_structural_completeness_does_not_claim_engineering_readiness(self):
        result = workflow.check_spec(self.root, self.spec)
        self.assertTrue(result["intake_complete"], result)
        self.assertFalse(result["simulation_ready"])
        self.assertTrue(result["pending_reviews"])

    def test_invalid_types_and_bounds_are_rejected(self):
        invalid = [
            ("schema_version", True), ("schema_version", 1.0),
            ("heat_flux_W_m2", True), ("heat_flux_W_m2", float("nan")),
            ("inlet_temperature_K", float("inf")),
            ("mass_flow_bounds_kg_s", [2, 1]),
            ("mass_flow_bounds_kg_s", [False, 1]),
            ("outlet_absolute_pressure_bounds_Pa", [0, 1]),
            ("geometry_changes_allowed", "false"),
            ("heated_faces", []), ("operating_mode", "transient"),
        ]
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                result = workflow.check_spec(self.root, {**self.spec, field: value})
                self.assertFalse(result["intake_complete"], result)

    def test_ambiguous_heat_load_is_rejected(self):
        result = workflow.check_spec(self.root, {**self.spec, "total_heat_load_W": 10})
        self.assertFalse(result["intake_complete"])

    def test_prepare_snapshots_preserves_inputs_and_records_no_execution(self):
        result = self.prepare()
        folder = self.root / result["run_directory"]
        self.assertEqual(result["status"], "prepared_only")
        self.assertFalse(result["simulation_executed"])
        self.assertEqual(result["jobs"], [])
        self.assertTrue(all(stage["status"] == "not_started" for stage in result["stages"]))
        self.assertEqual((folder / "project.json").read_bytes(), (self.root / "project.json").read_bytes())
        self.assertFalse(json.loads((folder / "project.json").read_text())["geometry_changes_allowed"])
        self.cad.write_bytes(b"source changes after preparation\n")
        checked = workflow.status(self.root, result["run_directory"])
        self.assertTrue(all(item["matches_snapshot"] for item in checked["snapshot_integrity"]))
        self.assertEqual((folder / "inputs/fixture.step").read_bytes(), b"fixture only, not an engineering STEP file\n")

    def test_snapshot_tampering_and_missing_input_are_reported(self):
        result = self.prepare()
        folder = self.root / result["run_directory"]
        (folder / "project.json").write_text("{}")
        (folder / "inputs/fixture.step").unlink()
        checked = workflow.status(self.root, result["run_directory"])
        self.assertEqual([x["matches_snapshot"] for x in checked["snapshot_integrity"]], [False, False])

    def test_repeated_prepare_gets_distinct_directories(self):
        first = self.prepare()
        second = self.prepare()
        self.assertNotEqual(first["run_directory"], second["run_directory"])

    def test_external_paths_and_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as external:
            external_path = Path(external) / "outside.step"
            external_path.write_text("outside")
            (self.root / "inputs/linked.step").symlink_to(external_path)
            for path in (str(external_path), "inputs/linked.step"):
                with self.subTest(path=path):
                    result = workflow.check_spec(self.root, {**self.spec, "cad_file": path})
                    self.assertFalse(result["intake_complete"])


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.root_patch = patch.object(workbench, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def run_fixture(self, code, timeout=5):
        source = self.root / "fixture.py"
        source.write_text(code)
        args = SimpleNamespace(command=[sys.executable, str(source)],
                               timeout=timeout, cwd=".", input=["fixture.py"],
                               label="verification-fixture")
        with contextlib.redirect_stdout(io.StringIO()):
            result = workbench.run_job(args)
        records = list((self.root / "runs").glob("*/job.json"))
        self.assertEqual(len(records), 1)
        return result, json.loads(records[0].read_text()), source

    def test_nonzero_exit_preserved_without_verification_claim(self):
        result, record, source = self.run_fixture("raise SystemExit(7)\n")
        self.assertEqual(result, 1)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["exit_code"], 7)
        self.assertFalse(record["numerically_verified"])
        self.assertEqual(record["inputs"][0]["sha256"], workbench.digest(source))

    def test_timeout_stops_child_and_records_failure(self):
        result, record, _ = self.run_fixture("import time\ntime.sleep(10)\n", timeout=0.1)
        self.assertEqual(result, 1)
        self.assertEqual(record["status"], "timed_out")
        self.assertIsNotNone(record["exit_code"])
        self.assertFalse(record["numerically_verified"])

    def test_second_job_lock_is_rejected(self):
        with workbench.job_lock():
            with self.assertRaisesRegex(RuntimeError, "Another recorded job"):
                with workbench.job_lock():
                    self.fail("Concurrent recorder lock was granted")

    def test_working_directory_cannot_escape_root(self):
        args = SimpleNamespace(command=[sys.executable, "-V"], timeout=5,
                               cwd="..", input=[], label="escape-fixture")
        with self.assertRaises(ValueError):
            workbench.run_job(args)
        self.assertFalse((self.root / "runs").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
