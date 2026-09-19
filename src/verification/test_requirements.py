"""Requirements guardrail tests. All approvals are synthetic and temporary."""
from concurrent.futures import ThreadPoolExecutor
import copy
from http.client import HTTPConnection
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.requirements import review
from src.requirements import server
from src import workflow


class RequirementsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="requirements-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.folder = self.root / "review"
        self.source = self.root / "fixture.step"
        self.source.write_bytes(b"Synthetic fixture only; not usable STEP geometry.\n")
        self.model = {
            "source": {"sha256": review.file_hash(self.source)},
            "import_fingerprint": "synthetic-import-v1", "units": "mm",
            "solid_count": 1,
            "faces": [{"id": "wall", "kind": "cad_face"},
                      {"id": "other", "kind": "cad_face"}],
            "virtual_faces": [{"id": "in", "kind": "virtual_cap"},
                              {"id": "out", "kind": "virtual_cap"}],
        }
        self.initial = review.initialize_review(self.folder, self.source, self.model)

    def complete_payload(self):
        req = review.defaults()
        req.update(title="Synthetic fixture", units_confirmed=True,
                   solid_material="Explicit fixture solid", coolant_material="Explicit fixture coolant",
                   inlet_temperature_K=300, maximum_surface_temperature_K=350,
                   objective="Check selected heated-surface maximum temperature",
                   other_thermal_boundaries="Explicit fixture insulation",
                   mass_flow_bounds_kg_s=[0.01, 0.02],
                   outlet_absolute_pressure_bounds_Pa=[100000, 200000],
                   heat_load={"mode": "total_heat_load_W", "value": 100})
        return {"requirements": req,
                "selections": {"inlet": ["in"], "outlet": ["out"], "heated": ["wall"]}}

    def save_complete(self):
        current = review.read_state(self.folder)
        return review.save_draft(self.folder, self.complete_payload(), current["draft"]["revision"])

    def approve_fixture(self, state=None):
        state = state or self.save_complete()
        return review.approve(self.folder, state["draft"]["revision"], state["draft_sha256"],
                              True, "SYNTHETIC TEST ONLY")

    def make_handoff(self):
        self.approve_fixture()
        return Path(review.handoff(self.folder)["handoff_directory"])

    def test_pump_limit_is_distinct_from_outlet_and_survives_handoff(self):
        payload = self.complete_payload()
        payload['requirements']['max_pump_pressure_rise_Pa'] = 800000
        payload['requirements']['outlet_absolute_pressure_bounds_Pa'] = [101325, 101325]
        state = review.save_draft(self.folder, payload, 0)
        self.assertEqual(state['issues'], [])
        self.approve_fixture(state)
        folder = Path(review.handoff(self.folder)['handoff_directory'])
        project = json.loads((folder / 'project.json').read_text())
        self.assertEqual(project['max_pump_pressure_rise_Pa'], 800000)
        self.assertEqual(project['outlet_absolute_pressure_bounds_Pa'], [101325, 101325])

    def test_invalid_pump_limits_block_approval(self):
        for value in (0, -1, True, '8'):
            req = self.complete_payload()['requirements']
            req['max_pump_pressure_rise_Pa'] = value
            self.assertIn('max_pump_pressure_rise', review.bounds_errors(req))
        req['max_pump_pressure_rise_Pa'] = None
        self.assertNotIn('max_pump_pressure_rise', review.bounds_errors(req))

    def test_initial_values_are_unresolved_and_cannot_handoff(self):
        self.assertFalse(self.initial["approved"])
        self.assertIsNone(self.initial["approval"])
        for key in ("solid_material", "coolant_material", "other_thermal_boundaries"):
            self.assertEqual(self.initial["draft"]["requirements"][key], "")
        self.assertIsNone(self.initial["draft"]["requirements"]["heat_load"]["value"])
        self.assertTrue(self.initial["issues"])
        with self.assertRaises(ValueError):
            review.handoff(self.folder)
        with self.assertRaises(ValueError):
            self.approve_fixture(self.initial)

    def test_saving_complete_draft_never_approves_or_executes(self):
        with patch("subprocess.Popen", side_effect=AssertionError("Unexpected execution")):
            state = self.save_complete()
        self.assertEqual(state["issues"], [])
        self.assertFalse(state["approved"])
        with self.assertRaises(ValueError):
            review.handoff(self.folder)

    def test_confirmation_requires_true_and_reviewer(self):
        state = self.save_complete()
        for confirmed, reviewer in ((False, "test"), (1, "test"), ("true", "test"),
                                    (True, ""), (True, "  ")):
            with self.subTest(confirmed=confirmed, reviewer=reviewer), self.assertRaises(ValueError):
                review.approve(self.folder, 1, state["draft_sha256"], confirmed, reviewer)
        self.assertFalse(review.read_state(self.folder)["approved"])

    def test_approval_binds_source_model_draft_revision_and_time(self):
        approved = self.approve_fixture()
        record = approved["approval"]
        self.assertTrue(approved["approved"])
        self.assertEqual(record["source_sha256"], review.file_hash(self.folder / "inputs/source.step"))
        self.assertEqual(record["model_sha256"], review.file_hash(self.folder / "model.json"))
        self.assertEqual(record["draft_sha256"], review.content_hash(approved["draft"]))
        self.assertEqual(record["revision"], approved["draft"]["revision"])
        self.assertTrue(record["approved_at"])

    def test_any_saved_edit_invalidates_approval(self):
        approved = self.approve_fixture()
        payload = self.complete_payload()
        payload["requirements"]["notes"] = "changed request"
        changed = review.save_draft(self.folder, payload, approved["draft"]["revision"])
        self.assertFalse(changed["approved"])
        self.assertIsNone(changed["approval"])
        with self.assertRaises(ValueError):
            review.handoff(self.folder)
        with self.assertRaises(review.ConflictError):
            self.approve_fixture(approved)

    def test_stale_save_and_wrong_display_hash_are_rejected(self):
        state = self.save_complete()
        for revision in (0, True, 1.0):
            with self.subTest(revision=revision), self.assertRaises(review.ConflictError):
                review.save_draft(self.folder, self.complete_payload(), revision)
        with self.assertRaises(review.ConflictError):
            review.approve(self.folder, 1, "wrong", True, "SYNTHETIC TEST")
        self.assertEqual(review.read_state(self.folder)["draft_sha256"], state["draft_sha256"])

    def test_concurrent_writers_cannot_both_save_same_revision(self):
        barrier = threading.Barrier(2)
        def write():
            barrier.wait()
            try:
                review.save_draft(self.folder, self.complete_payload(), 0)
                return "saved"
            except review.ConflictError:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: write(), range(2)))
        self.assertEqual(sorted(outcomes), ["conflict", "saved"])
        self.assertEqual(review.read_state(self.folder)["draft"]["revision"], 1)

    def test_invalid_boundary_assignments_are_rejected(self):
        cases = [{"inlet": ["missing"], "outlet": ["out"], "heated": ["wall"]},
                 {"inlet": ["in"], "outlet": ["in"], "heated": ["wall"]},
                 {"inlet": ["in", "in"], "outlet": ["out"], "heated": ["wall"]},
                 {"inlet": ["wall"], "outlet": ["out"], "heated": ["in"]}]
        for selections in cases:
            payload = self.complete_payload()
            payload["selections"] = selections
            with self.subTest(selections=selections), self.assertRaises(ValueError):
                review.save_draft(self.folder, payload, 0)

    def test_missing_or_invalid_physics_never_approves(self):
        cases = [("solid_material", ""), ("coolant_material", ""),
                 ("inlet_temperature_K", None), ("maximum_surface_temperature_K", None),
                 ("other_thermal_boundaries", ""), ("objective", ""),
                 ("units_confirmed", False), ("mass_flow_bounds_kg_s", [2, 1]),
                 ("outlet_absolute_pressure_bounds_Pa", [0, 1]),
                 ("heat_load", {"mode": "total_heat_load_W", "value": True}),
                 ("temperature_limit_scope", "unspecified"),
                 ("operating_mode", "transient"), ("heat_direction", "out_of_solid"),
                 ("geometry_changes_allowed", True)]
        for key, value in cases:
            payload = self.complete_payload()
            payload["requirements"][key] = value
            revision = review.read_state(self.folder)["draft"]["revision"]
            state = review.save_draft(self.folder, payload, revision)
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.approve_fixture(state)

    def test_nonfinite_input_rejected_without_mutating_review(self):
        payload = self.complete_payload()
        payload["requirements"]["inlet_temperature_K"] = float("nan")
        before = (self.folder / "review.json").read_bytes()
        with self.assertRaises(ValueError):
            review.save_draft(self.folder, payload, 0)
        self.assertEqual((self.folder / "review.json").read_bytes(), before)

    def save_pressure_bounds(self, bounds):
        payload = self.complete_payload()
        payload["requirements"]["outlet_absolute_pressure_bounds_Pa"] = bounds
        revision = review.read_state(self.folder)["draft"]["revision"]
        saved = review.save_draft(self.folder, payload, revision)
        reloaded = review.read_state(self.folder)
        self.assertEqual(saved, reloaded)
        self.assertEqual(reloaded["draft"]["requirements"]["outlet_absolute_pressure_bounds_Pa"], bounds)
        return reloaded

    def test_blank_pressure_bound_is_an_open_range_not_an_issue(self):
        for bounds in ([None, 60005], [60005, None]):
            with self.subTest(bounds=bounds):
                state = self.save_pressure_bounds(bounds)
                self.assertEqual(state["issues"], [])
                self.assertEqual(state["field_errors"], {})
                self.assertTrue(self.approve_fixture(state)["approved"])

    def test_blank_flow_and_pressure_bounds_approve_and_hand_off_for_autofill(self):
        payload = self.complete_payload()
        payload["requirements"]["mass_flow_bounds_kg_s"] = [None, None]
        payload["requirements"]["outlet_absolute_pressure_bounds_Pa"] = [None, None]
        revision = review.read_state(self.folder)["draft"]["revision"]
        state = review.save_draft(self.folder, payload, revision)
        self.assertEqual(state["issues"], [])
        self.assertTrue(self.approve_fixture(state)["approved"])
        package = Path(review.handoff(self.folder)["handoff_directory"])
        project = json.loads((package / "project.json").read_text())
        self.assertEqual(project["mass_flow_bounds_kg_s"], [None, None])
        self.assertEqual(project["outlet_absolute_pressure_bounds_Pa"], [None, None])
        self.assertEqual(review.verify_handoff(package)["valid"], True)

    def test_zero_absolute_pressure_is_saved_but_reported_as_invalid_not_missing(self):
        state = self.save_pressure_bounds([0, 60005])
        message = " ".join(state["issues"]).lower()
        self.assertIn("lower", message)
        self.assertIn("absolute", message)
        self.assertRegex(message, r"zero|0")
        self.assertNotIn("missing", message)
        self.assertNotIn("is required", message)
        self.assertFalse(state["approved"])
        with self.assertRaises(ValueError):
            self.approve_fixture(state)

    def test_reversed_positive_pressure_bounds_are_explained(self):
        state = self.save_pressure_bounds([60005, 50000])
        message = " ".join(state["issues"]).lower()
        self.assertIn("pressure", message)
        self.assertIn("lower", message)
        self.assertIn("upper", message)
        self.assertNotIn("missing", message)
        with self.assertRaises(ValueError):
            self.approve_fixture(state)

    def test_equal_positive_pressure_bounds_are_a_valid_fixed_pressure(self):
        state = self.save_pressure_bounds([60005, 60005])
        self.assertEqual(state["issues"], [])
        self.assertFalse(state["approved"])
        self.assertTrue(self.approve_fixture(state)["approved"])

    def test_valid_positive_pressure_bounds_survive_save_and_reload(self):
        state = self.save_pressure_bounds([50000, 60005])
        self.assertEqual(state["issues"], [])
        self.assertFalse(state["approved"])
        self.assertIsNone(state["approval"])

    def test_nonfinite_pressure_cannot_overwrite_saved_draft(self):
        self.save_pressure_bounds([50000, 60005])
        before = (self.folder / "review.json").read_bytes()
        for value in (float("nan"), float("inf"), float("-inf")):
            for index in (0, 1):
                payload = self.complete_payload()
                payload["requirements"]["outlet_absolute_pressure_bounds_Pa"][index] = value
                with self.subTest(value=value, index=index), self.assertRaises(ValueError):
                    review.save_draft(self.folder, payload, 1)
                self.assertEqual((self.folder / "review.json").read_bytes(), before)

    def save_gauge_pressure(self, raw_bounds, reference, absolute_bounds):
        payload = self.complete_payload()
        payload["requirements"]["pressure_input"] = {
            "mode": "gauge", "bounds_Pa": raw_bounds,
            "reference_pressure_Pa": reference,
        }
        payload["requirements"]["outlet_absolute_pressure_bounds_Pa"] = absolute_bounds
        revision = review.read_state(self.folder)["draft"]["revision"]
        return review.save_draft(self.folder, payload, revision)

    def test_zero_gauge_with_explicit_reference_converts_to_positive_absolute(self):
        state = self.save_gauge_pressure([0, 60005], 101325, [101325, 161330])
        self.assertEqual(state["issues"], [])
        reloaded = review.read_state(self.folder)
        self.assertEqual(state, reloaded)
        req = reloaded["draft"]["requirements"]
        self.assertEqual(req["pressure_input"]["bounds_Pa"], [0, 60005])
        self.assertEqual(req["pressure_input"]["reference_pressure_Pa"], 101325)
        self.assertEqual(req["outlet_absolute_pressure_bounds_Pa"], [101325, 161330])
        self.assertFalse(state["approved"])
        approved = self.approve_fixture(state)
        self.assertTrue(approved["approved"])
        package = Path(review.handoff(self.folder)["handoff_directory"])
        self.assertTrue(review.verify_handoff(package)["valid"])
        self.assertEqual(json.loads((package / "project.json").read_text())["outlet_absolute_pressure_bounds_Pa"],
                         [101325, 161330])
        self.assertEqual(json.loads((package / "requirements.json").read_text())["requirements"]["pressure_input"],
                         req["pressure_input"])

    def test_gauge_pressure_requires_explicit_positive_reference(self):
        for reference in (None, 0, -1):
            with self.subTest(reference=reference):
                state = self.save_gauge_pressure([0, 60005], reference, [None, None])
                message = " ".join(state["issues"]).lower()
                self.assertIn("reference", message)
                self.assertFalse(state["approved"])
                with self.assertRaises(ValueError):
                    self.approve_fixture(state)
                self.assertEqual(state["draft"]["requirements"]["pressure_input"]["reference_pressure_Pa"], reference)

    def test_gauge_conversion_mismatch_cannot_approve(self):
        state = self.save_gauge_pressure([0, 60005], 101325, [10000, 60005])
        self.assertTrue(state["issues"])
        self.assertFalse(state["approved"])
        with self.assertRaises(ValueError):
            self.approve_fixture(state)

    def test_blank_gauge_bound_needs_a_matching_blank_absolute_bound(self):
        for raw_bounds, absolute in (([None, 60005], [None, 161330]), ([0, None], [101325, None])):
            with self.subTest(raw_bounds=raw_bounds):
                state = self.save_gauge_pressure(raw_bounds, 101325, absolute)
                self.assertEqual(state["issues"], [])
        for raw_bounds in ([None, 60005], [0, None]):
            with self.subTest(raw_bounds=raw_bounds, stored="stale"):
                state = self.save_gauge_pressure(raw_bounds, 101325, [None, None])
                self.assertTrue(state["issues"])
                with self.assertRaises(ValueError):
                    self.approve_fixture(state)

    def test_blank_gauge_bounds_need_no_reference(self):
        state = self.save_gauge_pressure([None, None], None, [None, None])
        self.assertEqual(state["issues"], [])
        self.assertTrue(self.approve_fixture(state)["approved"])

    def test_negative_gauge_allowed_when_resulting_absolute_pressure_is_positive(self):
        state = self.save_gauge_pressure([-10000, 0], 101325, [91325, 101325])
        self.assertEqual(state["issues"], [])

    def test_legacy_pressure_without_input_metadata_remains_absolute(self):
        state = self.save_pressure_bounds([10000, 60005])
        self.assertNotIn("pressure_input", state["draft"]["requirements"])
        self.assertEqual(state["draft"]["requirements"]["outlet_absolute_pressure_bounds_Pa"], [10000, 60005])
        self.assertEqual(state["issues"], [])

    def test_changed_source_blocks_approval_and_handoff(self):
        state = self.save_complete()
        (self.folder / "inputs/source.step").write_bytes(b"changed")
        with self.assertRaises(review.ConflictError):
            self.approve_fixture(state)
        with self.assertRaises(review.ConflictError):
            review.handoff(self.folder)

    def test_changed_model_blocks_existing_approval(self):
        self.approve_fixture()
        (self.folder / "model.json").write_text("{}")
        with self.assertRaises(review.ConflictError):
            review.handoff(self.folder)

    def test_direct_draft_edit_cannot_reuse_approval(self):
        self.approve_fixture()
        path = self.folder / "review.json"
        record = json.loads(path.read_text())
        record["draft"]["requirements"]["heat_load"]["value"] = 200
        path.write_text(json.dumps(record))
        self.assertFalse(review.read_state(self.folder)["approved"])
        with self.assertRaises(ValueError):
            review.handoff(self.folder)

    def test_handoff_copies_versioned_package_and_preserves_prior_version(self):
        before = self.source.read_bytes()
        first = self.make_handoff()
        hashes = {path.name: review.file_hash(path) for path in first.iterdir()}
        second = Path(review.handoff(self.folder)["handoff_directory"])
        self.assertNotEqual(first, second)
        self.assertTrue(review.verify_handoff(first)["valid"])
        self.assertFalse(json.loads((first / "manifest.json").read_text())["simulation_ready"])
        self.assertEqual(json.loads((first / "project.json").read_text())["temperature_limit_scope"],
                         "heated_surfaces")
        self.save_complete()
        self.assertEqual(hashes, {path.name: review.file_hash(path) for path in first.iterdir()})
        self.assertTrue(review.verify_handoff(first)["valid"])
        self.assertEqual(self.source.read_bytes(), before)

    def test_changed_handoff_snapshot_rejected(self):
        folder = self.make_handoff()
        (folder / "source.step").write_bytes(b"changed")
        with self.assertRaises(review.ConflictError):
            review.verify_handoff(folder)

    def test_manifest_semantics_must_match_approved_snapshots(self):
        folder = self.make_handoff()
        path = folder / "manifest.json"
        original = json.loads(path.read_text())
        for key, value in (("source_sha256", "wrong"), ("model_sha256", "wrong"),
                           ("import_fingerprint", "wrong"), ("approval", None),
                           ("boundary_mapping", [])):
            modified = copy.deepcopy(original)
            modified[key] = value
            path.write_text(json.dumps(modified))
            with self.subTest(key=key), self.assertRaises(ValueError):
                review.verify_handoff(folder)
        path.write_text(json.dumps(original))

    def test_exported_physics_cannot_disagree_with_approved_draft(self):
        folder = self.make_handoff()
        path = folder / "project.json"
        project = json.loads(path.read_text())
        project["total_heat_load_W"] = 200
        path.write_text(json.dumps(project))
        manifest_path = folder / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["project.json"] = review.file_hash(path)
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            review.verify_handoff(folder)

    def test_prepared_run_preserves_verified_approval_package(self):
        handoff = self.make_handoff()
        state = workflow.prepare(self.root, str(handoff / "project.json"), "fixture")
        copied = self.root / state["run_directory"] / "requirements_review"
        self.assertTrue(review.verify_handoff(handoff)["valid"])
        # Archive copies retain original absolute paths and are evidence, not
        # relocated executable handoffs. Relocation is explicitly unsupported.
        with self.assertRaises(review.ConflictError):
            review.verify_handoff(copied)
        self.assertFalse(state["simulation_executed"])
        for name in ("source.step", "model.json", "requirements.json", "approval.json", "manifest.json"):
            self.assertEqual((copied / name).read_bytes(), (handoff / name).read_bytes())
        status = workflow.status(self.root, state["run_directory"])
        self.assertTrue(all(item["matches_snapshot"] for item in status["snapshot_integrity"]))
        (copied / "approval.json").write_text("{}")
        status = workflow.status(self.root, state["run_directory"])
        self.assertFalse(all(item["matches_snapshot"] for item in status["snapshot_integrity"]))

    def test_prepare_rejects_tampered_package_before_creating_run(self):
        handoff = self.make_handoff()
        (handoff / "source.step").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            workflow.prepare(self.root, str(handoff / "project.json"), "fixture")
        self.assertFalse((self.root / "runs").exists())

    def test_prepare_rejects_detached_or_modified_project(self):
        handoff = self.make_handoff()
        detached = self.root / "detached.json"
        detached.write_bytes((handoff / "project.json").read_bytes())
        with self.assertRaises(ValueError):
            workflow.prepare(self.root, str(detached), "fixture")
        project = json.loads((handoff / "project.json").read_text())
        project["heat_flux_W_m2"] = 500
        (handoff / "project.json").write_text(json.dumps(project))
        with self.assertRaises(ValueError):
            workflow.prepare(self.root, str(handoff / "project.json"), "fixture")
        self.assertFalse((self.root / "runs").exists())

    def test_http_requires_local_token_current_revision_and_confirmation(self):
        service = server.make_server(self.folder, port=0)
        worker = threading.Thread(target=lambda: service.serve_forever(poll_interval=0.01))
        worker.start()
        def cleanup():
            service.shutdown()
            service.server_close()
            worker.join(timeout=2)
        self.addCleanup(cleanup)
        port = service.server_port
        def request(method, route, payload=None, headers=None):
            connection = HTTPConnection("127.0.0.1", port, timeout=3)
            try:
                connection.request(method, route,
                                   body=json.dumps(payload) if payload is not None else None,
                                   headers=headers or {})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()
        status, initial = request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertFalse(initial["approved"])
        token = {"X-Review-Token": initial["csrf_token"], "Content-Type": "application/json"}
        payload = {"draft": self.complete_payload(), "expected_revision": 0}
        self.assertEqual(request("POST", "/api/draft", payload)[0], 403)
        self.assertEqual(request("POST", "/api/draft", payload,
                                 {**token, "Origin": "https://external.invalid"})[0], 403)
        status, saved = request("POST", "/api/draft", payload, token)
        self.assertEqual(status, 200)
        self.assertFalse(saved["approved"])
        self.assertEqual(request("POST", "/api/draft", payload, token)[0], 409)
        self.assertEqual(request("POST", "/api/handoff", {}, token)[0], 400)
        approval = {"expected_revision": saved["draft"]["revision"],
                    "draft_sha256": saved["draft_sha256"], "reviewer": "SYNTHETIC HTTP TEST"}
        self.assertEqual(request("POST", "/api/approve", approval, token)[0], 400)
        status, approved = request("POST", "/api/approve", {**approval, "confirmed": True}, token)
        self.assertEqual(status, 200)
        self.assertTrue(approved["approved"])
        status, result = request("POST", "/api/handoff", {}, token)
        self.assertEqual(status, 200)
        self.assertTrue(review.verify_handoff(result["handoff_directory"])["valid"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
