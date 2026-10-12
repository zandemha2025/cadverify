"""These synthetic unit fixtures test the accounting guardrails, not real integrations."""

import copy
from contextlib import redirect_stderr
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest


MODULE_PATH = Path(__file__).parents[1] / "readiness.py"
SPEC = importlib.util.spec_from_file_location("readiness", MODULE_PATH)
readiness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(readiness)
REGISTRY = MODULE_PATH.with_name("registry.json")


class EvidenceAccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def artifact(self, name, payload, kind=None):
        path = self.root / name
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        ref = {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        if kind:
            ref["kind"] = kind
        return ref

    def evidence(self, env_class="self_hosted_oss_test", stages=None, run_id="unit-fixture-1"):
        # A real-class label in a unit fixture is never a real test receipt.
        manifest = self.artifact(f"{run_id}-tenant.json", {
            "operator_reviewed": True, "provider_id": "keycloak",
            "environment_class": env_class, "environment_id": "unit-fixture",
            "base_url": "http://unit-fixture.invalid", "authorization_reference": "unit test only",
        })
        manifest.update(reviewed_by="unit test", reviewed_at="2026-10-10T00:00:00Z")
        selected = list(readiness.STAGES if stages is None else stages)
        result = {
            "schema_version": 1, "run_id": run_id, "workflow_id": "keycloak_oidc",
            "provider_id": "keycloak", "environment_class": env_class,
            "environment": {"id": "unit-fixture", "base_url": "http://unit-fixture.invalid"},
            "source": {"commit": "a" * 40, "build_id": "unit-fixture"},
            "authorization": {"scope": "unit test only", "reference": "unit test only"},
            "tenant_manifest": manifest, "started_at": "2026-10-10T00:00:01Z",
            "completed_at": "2026-10-10T00:00:10Z", "vendor_attempt_count": 0, "stages": [],
        }
        for stage_id in selected:
            stage = {
                "stage_id": stage_id, "outcome": "PASS", "independently_observed_action": True,
                "action_description": "Synthetic unit test fixture, not a real external action",
                "request_id": f"{run_id}-{stage_id}-request",
                "provider_receipt_id": f"{run_id}-{stage_id}-receipt",
                "acceptance_review": {"reviewed_by": "unit test", "reference": "unit test only",
                                      "reviewed_at": "2026-10-10T00:00:09Z"},
                "artifacts": [
                    self.artifact(f"{run_id}-{stage_id}-external.json", {"fixture": True, "stage": stage_id}, "provider_receipt"),
                    self.artifact(f"{run_id}-{stage_id}-runtime.json", {"fixture": True, "observed": stage_id}, "runtime_observation"),
                ],
            }
            if stage_id == "functional_action":
                stage["acceptance_checks"] = {
                    "provider_login": "PASS", "authorization_code_callback": "PASS", "mapped_user_session": "PASS",
                }
            if stage_id == "source_result_reconciliation":
                source = self.artifact(f"{run_id}-source.json", {"subject": "synthetic-user"}, "source_snapshot")
                target = self.artifact(f"{run_id}-result.json", {"subject": "synthetic-user"}, "result_snapshot")
                diff = self.artifact(f"{run_id}-diff.json", {
                    "compared_fields": ["subject"], "missing_count": 0, "extra_count": 0, "changed_count": 0,
                }, "reconciliation_report")
                stage["artifacts"].extend([source, target, diff])
                stage["reconciliation"] = {
                    "source_artifact": source["path"], "result_artifact": target["path"], "diff_artifact": diff["path"],
                    "missing_count": 0, "extra_count": 0, "changed_count": 0,
                }
            result["stages"].append(stage)
        return result

    def write_run(self, run, name="run.json"):
        path = self.root / name
        path.write_text(json.dumps(run), encoding="utf-8")
        return path

    def score(self, *runs):
        return readiness.audit(REGISTRY, [self.write_run(r, f"run-{i}.json") for i, r in enumerate(runs)], self.root)

    def row(self, report, name="keycloak_oidc"):
        return next(r for r in report["workflows"] if r["id"] == name)

    def test_no_evidence_is_zero_not_failure_or_known_zero_attempts(self):
        report = readiness.audit(REGISTRY, [], self.root)
        self.assertEqual(len(report["workflows"]), 19)
        for row in report["workflows"]:
            self.assertEqual((row["numerator"], row["denominator"], row["real_system_percentage"]), (0, 6, 0))
            self.assertTrue(all(s["status"] == "NOT_DEMONSTRATED" for s in row["stages"]))
            self.assertEqual(row["vendor_attempts"]["status"], "UNKNOWN")

    def test_mock_fixture_and_simulator_passes_never_receive_real_credit(self):
        for env_class in ("mock", "fixture", "simulator"):
            with self.subTest(env_class=env_class):
                row = self.row(self.score(self.evidence(env_class)))
                self.assertEqual(row["numerator"], 0)
                self.assertEqual(sum(s["mock_fixture_passes"] for s in row["stages"]), 6)
                self.assertEqual(row["vendor_attempts"]["status"], "KNOWN")

    def test_real_oss_target_is_isolated_and_denominator_is_fixed(self):
        report = self.score(self.evidence(stages=["authentication_transport"]))
        self.assertEqual(self.row(report)["real_system_percentage"], 16.67)
        self.assertEqual(self.row(report)["denominator"], 6)
        self.assertTrue(all(r["numerator"] == 0 for r in report["workflows"] if r["id"] != "keycloak_oidc"))
        self.assertEqual(self.row(self.score(self.evidence()))["real_system_percentage"], 100)

    def test_keycloak_cannot_credit_okta(self):
        run = self.evidence()
        run["workflow_id"] = "okta_oidc"
        with self.assertRaisesRegex(readiness.EvidenceError, "provider/workflow mismatch"):
            self.score(run)

    def test_named_vendor_cannot_claim_self_hosted_oss_credit(self):
        run = self.evidence()
        run["workflow_id"] = "okta_oidc"
        run["provider_id"] = "okta"
        with self.assertRaisesRegex(readiness.EvidenceError, "environment class is not valid"):
            self.score(run)

    def test_mock_manifest_cannot_be_relabelled_vendor(self):
        run = self.evidence("fixture")
        run["workflow_id"] = "okta_oidc"
        run["provider_id"] = "okta"
        run["environment_class"] = "vendor_sandbox"
        run["vendor_attempt_count"] = 1
        with self.assertRaisesRegex(readiness.EvidenceError, "manifest identity/class/authorization mismatch"):
            self.score(run)

    def test_missing_and_tampered_artifacts_are_rejected(self):
        for kind in ("missing", "tampered"):
            with self.subTest(kind=kind):
                run = self.evidence(stages=["authentication_transport"])
                artifact = self.root / run["stages"][0]["artifacts"][0]["path"]
                artifact.unlink() if kind == "missing" else artifact.write_text("tampered")
                with self.assertRaises(readiness.EvidenceError):
                    self.score(run)

    def test_reconciliation_requires_zero_counts_and_equal_nonempty_snapshots(self):
        for variant in ("nonzero", "different_snapshot", "empty_projection", "missing_diff", "type_mismatch"):
            with self.subTest(variant=variant):
                run = self.evidence(stages=["source_result_reconciliation"])
                stage = run["stages"][0]
                if variant == "nonzero":
                    stage["reconciliation"]["changed_count"] = 1
                elif variant in ("different_snapshot", "empty_projection"):
                    target = next(a for a in stage["artifacts"] if a["kind"] == "result_snapshot")
                    value = {} if variant == "empty_projection" else {"subject": "different"}
                    target.update(self.artifact(target["path"], value, "result_snapshot"))
                elif variant == "type_mismatch":
                    source = next(a for a in stage["artifacts"] if a["kind"] == "source_snapshot")
                    target = next(a for a in stage["artifacts"] if a["kind"] == "result_snapshot")
                    source.update(self.artifact(source["path"], {"active": True}, "source_snapshot"))
                    target.update(self.artifact(target["path"], {"active": 1}, "result_snapshot"))
                else:
                    stage["artifacts"] = [a for a in stage["artifacts"] if a["kind"] != "reconciliation_report"]
                with self.assertRaises(readiness.EvidenceError):
                    self.score(run)

    def test_connected_flag_without_runtime_action_has_no_credit(self):
        run = self.evidence(stages=["configuration_trust"])
        run["stages"][0]["independently_observed_action"] = False
        with self.assertRaisesRegex(readiness.EvidenceError, "observed external/runtime action"):
            self.score(run)

    def test_functional_action_requires_complete_workflow_checks(self):
        run = self.evidence(stages=["functional_action"])
        del run["stages"][0]["acceptance_checks"]["mapped_user_session"]
        with self.assertRaisesRegex(readiness.EvidenceError, "every workflow-specific acceptance check"):
            self.score(run)

    def test_duplicate_and_unknown_receipts_stages_and_workflows_are_rejected(self):
        run = self.evidence(stages=["authentication_transport"])
        for variant in ("duplicate_run", "duplicate_receipt", "duplicate_stage", "unknown_stage", "unknown_workflow"):
            with self.subTest(variant=variant):
                first = copy.deepcopy(run)
                second = copy.deepcopy(run)
                if variant == "duplicate_run":
                    runs = [first, second]
                elif variant == "duplicate_receipt":
                    second["run_id"] = "second"
                    runs = [first, second]
                else:
                    if variant == "duplicate_stage":
                        first["stages"].append(copy.deepcopy(first["stages"][0]))
                    elif variant == "unknown_stage":
                        first["stages"][0]["stage_id"] = "invented"
                    else:
                        first["workflow_id"] = "invented"
                    runs = [first]
                with self.assertRaises(readiness.EvidenceError):
                    self.score(*runs)

    def test_latest_observed_failure_removes_current_credit(self):
        earlier = self.evidence(stages=["authentication_transport"], run_id="earlier")
        later = self.evidence(stages=["authentication_transport"], run_id="later")
        later["stages"][0]["outcome"] = "FAIL"
        later["completed_at"] = "2026-10-10T00:00:20Z"
        row = self.row(self.score(earlier, later))
        self.assertEqual(row["numerator"], 0)
        self.assertEqual(row["stages"][1]["status"], "FAIL")

    def test_simultaneous_contradictory_results_are_rejected(self):
        earlier = self.evidence(stages=["authentication_transport"], run_id="first")
        later = self.evidence(stages=["authentication_transport"], run_id="second")
        later["stages"][0]["outcome"] = "FAIL"
        with self.assertRaisesRegex(readiness.EvidenceError, "contradictory simultaneous outcomes"):
            self.score(earlier, later)

    def test_unknown_vendor_attempt_count_is_distinct_from_zero(self):
        run = self.evidence(stages=["authentication_transport"])
        self.assertEqual(self.row(self.score(run))["vendor_attempts"]["status"], "KNOWN")
        run["vendor_attempt_count"] = None
        self.assertEqual(self.row(self.score(run))["vendor_attempts"]["status"], "UNKNOWN")

    def test_different_source_builds_cannot_be_combined_into_workflow_credit(self):
        earlier = self.evidence(stages=["authentication_transport"], run_id="old-build")
        later = self.evidence(stages=["configuration_trust"], run_id="new-build")
        later["source"]["build_id"] = "different-build"
        later["completed_at"] = "2026-10-10T00:00:20Z"
        row = self.row(self.score(earlier, later))
        self.assertEqual(row["numerator"], 1)
        self.assertEqual(row["other_context_run_ids"], ["old-build"])
        self.assertEqual(row["selected_evidence_context"]["source"]["build_id"], "different-build")

    def test_artifact_path_cannot_escape_authorized_root(self):
        run = self.evidence(stages=["authentication_transport"])
        run["stages"][0]["artifacts"][0]["path"] = "../outside.json"
        with self.assertRaisesRegex(readiness.EvidenceError, "outside authorized root"):
            self.score(run)

    def test_cli_rejects_without_writing_partial_matrix(self):
        run = self.evidence(stages=["authentication_transport"])
        run["provider_id"] = "other"
        output = self.root / "result.json"
        code = readiness.main(["--registry", str(REGISTRY), "--artifact-root", str(self.root),
                               "--evidence", str(self.write_run(run)), "--output-json", str(output),
                               "--output-markdown", str(self.root / "result.md")])
        self.assertEqual(code, 2)
        self.assertFalse(output.exists())

    def test_nonfinite_json_constants_are_rejected_in_run_and_reconciliation(self):
        for constant in (float("nan"), float("inf"), float("-inf")):
            for location in ("run", "reconciliation"):
                with self.subTest(constant=constant, location=location):
                    run = self.evidence(stages=["source_result_reconciliation"])
                    if location == "run":
                        run["invalid_number"] = constant
                    else:
                        stage = run["stages"][0]
                        for artifact in stage["artifacts"]:
                            if artifact["kind"] in ("source_snapshot", "result_snapshot"):
                                artifact.update(self.artifact(artifact["path"], {"subject": constant}, artifact["kind"]))
                    with self.assertRaisesRegex(readiness.EvidenceError, "non-finite JSON constant"):
                        self.score(run)

    def test_vendor_malformed_stages_exit_two_without_traceback_or_output(self):
        for malformed in (None, "PASS", 123, ["stage"], {"not": "a list"}):
            with self.subTest(malformed=malformed):
                run = self.evidence(stages=[])
                run.update(workflow_id="okta_oidc", provider_id="okta", environment_class="vendor_sandbox",
                           vendor_attempt_count=0, stages=malformed if isinstance(malformed, dict) else [malformed])
                manifest_path = self.root / run["tenant_manifest"]["path"]
                manifest = json.loads(manifest_path.read_text())
                manifest.update(provider_id="okta", environment_class="vendor_sandbox")
                run["tenant_manifest"].update(self.artifact(manifest_path.name, manifest))
                with self.assertRaisesRegex(readiness.EvidenceError, "stages must be a list|stage must be an object"):
                    self.score(run)
                stderr = io.StringIO()
                output = self.root / "must-not-exist.json"
                with redirect_stderr(stderr):
                    code = readiness.main([
                        "--registry", str(REGISTRY), "--artifact-root", str(self.root),
                        "--evidence", str(self.write_run(run)), "--output-json", str(output),
                        "--output-markdown", str(self.root / "must-not-exist.md"),
                    ])
                self.assertEqual(code, 2)
                self.assertIn("Evidence rejected", stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())
                self.assertFalse(output.exists())

    def test_evidence_paths_are_relative_and_matrix_is_portable(self):
        run = self.evidence(stages=["authentication_transport"])
        original = self.score(run)
        stage = self.row(original)["stages"][1]
        self.assertEqual(stage["evidence_path"], "run-0.json")
        self.assertFalse(Path(stage["evidence_path"]).is_absolute())
        with tempfile.TemporaryDirectory() as destination:
            moved = Path(destination) / "relocated-bundle"
            shutil.copytree(self.root, moved)
            relocated = readiness.audit(REGISTRY, [moved / "run-0.json"], moved)
        self.assertEqual(original, relocated)


if __name__ == "__main__":
    unittest.main()
