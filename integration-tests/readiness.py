#!/usr/bin/env python3
"""Offline, fail-closed evidence accounting. It does not contact or certify providers."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from datetime import datetime


STAGES = (
    "configuration_trust", "authentication_transport", "functional_action",
    "source_result_reconciliation", "failure_handling", "recovery_retry",
)
REAL_CLASSES = {"vendor_sandbox", "customer_test_tenant", "self_hosted_oss_test"}
NONREAL_CLASSES = {"mock", "fixture", "simulator"}
DIFF_COUNTS = ("missing_count", "extra_count", "changed_count")


class EvidenceError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def timestamp(value):
    require(nonempty(value), "timestamp must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError("invalid ISO-8601 timestamp") from exc
    require(parsed.tzinfo is not None, "timestamp must include timezone")
    return parsed


def read_json(path):
    def reject_constant(value):
        raise EvidenceError(f"non-finite JSON constant is not allowed: {value}")
    try:
        return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    except (OSError, ValueError) as exc:
        raise EvidenceError(f"cannot read JSON {path}: {exc}") from exc


def checked_artifact(item, document_dir, root):
    require(isinstance(item, dict), "artifact must be an object")
    require(nonempty(item.get("path")), "artifact path is required")
    require(isinstance(item.get("sha256"), str) and
            re.fullmatch(r"[0-9a-f]{64}", item["sha256"]), "artifact SHA256 is required")
    path = (document_dir / item["path"]).resolve()
    require(path.is_relative_to(root), f"artifact outside authorized root: {item['path']}")
    require(path.is_file(), f"artifact is missing: {item['path']}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    require(digest == item["sha256"], f"artifact hash mismatch: {item['path']}")
    return path


def load_registry(path):
    registry = read_json(path)
    require(registry.get("schema_version") == 1, "unknown registry schema")
    require(tuple(s["id"] for s in registry["stages"]) == STAGES,
            "registry must retain exactly the six documented stages in order")
    identifiers = [w["id"] for w in registry["workflows"]]
    require(len(identifiers) == len(set(identifiers)), "duplicate registry workflow")
    require(all(nonempty(w.get("provider_id")) for w in registry["workflows"]),
            "registry provider identity is required")
    return registry


def validate_run(path, registry, root, seen_runs, seen_receipts):
    run = read_json(path)
    require(isinstance(run, dict) and run.get("schema_version") == 1, "unknown evidence schema")
    workflows = {w["id"]: w for w in registry["workflows"]}
    require(run.get("workflow_id") in workflows, "unknown workflow")
    workflow = workflows[run["workflow_id"]]
    require(run.get("provider_id") == workflow["provider_id"], "provider/workflow mismatch")
    require(nonempty(run.get("run_id")), "run_id is required")
    require(run["run_id"] not in seen_runs, "duplicate run_id")
    seen_runs.add(run["run_id"])
    env_class = run.get("environment_class")
    require(env_class in REAL_CLASSES | NONREAL_CLASSES, "unknown environment class")
    require(env_class in NONREAL_CLASSES or env_class in workflow["allowed_real_classes"],
            "environment class is not valid for this provider/workflow")
    if workflow["scope"] == "local_test_target":
        require(env_class in NONREAL_CLASSES | {"self_hosted_oss_test"},
                "local OSS workflow cannot claim a named vendor sandbox or customer tenant")
    started = timestamp(run.get("started_at"))
    completed = timestamp(run.get("completed_at"))
    require(completed >= started, "run completed before it started")
    source = run.get("source", {})
    require(isinstance(source, dict) and
            isinstance(source.get("commit"), str) and
            re.fullmatch(r"[0-9a-f]{40}", source["commit"]), "full source commit is required")
    require(nonempty(source.get("build_id")), "build_id is required")
    authorization = run.get("authorization", {})
    require(isinstance(authorization, dict) and nonempty(authorization.get("scope")) and
            nonempty(authorization.get("reference")), "authorization scope/reference is required")
    environment = run.get("environment", {})
    require(isinstance(environment, dict) and nonempty(environment.get("id")) and
            nonempty(environment.get("base_url")), "environment identity/base_url is required")
    manifest_ref = run.get("tenant_manifest", {})
    manifest_path = checked_artifact(manifest_ref, path.parent, root)
    require(nonempty(manifest_ref.get("reviewed_by")), "tenant manifest reviewer is required")
    require(timestamp(manifest_ref.get("reviewed_at")) <= completed,
            "tenant manifest review cannot be after the run")
    manifest = read_json(manifest_path)
    require(isinstance(manifest, dict), "tenant manifest must be an object")
    require(manifest.get("operator_reviewed") is True, "tenant manifest must be operator reviewed")
    expected = {
        "provider_id": run["provider_id"], "environment_class": env_class,
        "environment_id": environment["id"], "base_url": environment["base_url"],
        "authorization_reference": authorization["reference"],
    }
    require(all(manifest.get(k) == v for k, v in expected.items()),
            "tenant manifest identity/class/authorization mismatch")
    require(isinstance(run.get("stages"), list), "stages must be a list")
    require(all(isinstance(stage, dict) for stage in run["stages"]), "stage must be an object")
    attempts = run.get("vendor_attempt_count", "missing")
    require(attempts is None or (type(attempts) is int and attempts >= 0),
            "vendor_attempt_count must be explicit: nonnegative integer or null (unknown)")
    if env_class in NONREAL_CLASSES or env_class == "self_hosted_oss_test":
        require(attempts in (0, None), "mock/OSS run cannot claim named vendor attempts")
    elif any(s.get("outcome") == "PASS" for s in run["stages"]):
        require(type(attempts) is int and attempts >= 1,
                "passing vendor/customer evidence requires a known positive vendor_attempt_count")

    seen_stages = set()
    for stage in run["stages"]:
        require(isinstance(stage, dict), "stage must be an object")
        stage_id = stage.get("stage_id")
        require(stage_id in STAGES, "unknown stage")
        require(stage_id not in seen_stages, "duplicate/contradictory stage in run")
        seen_stages.add(stage_id)
        require(stage.get("outcome") in {"PASS", "FAIL", "NOT_DEMONSTRATED"}, "unknown outcome")
        artifacts = stage.get("artifacts", [])
        require(isinstance(artifacts, list), "stage artifacts must be a list")
        by_path = {}
        by_kind = {}
        for artifact in artifacts:
            artifact_path = checked_artifact(artifact, path.parent, root)
            require(artifact["path"] not in by_path, "duplicate stage artifact path")
            require(nonempty(artifact.get("kind")), "artifact kind is required")
            by_path[artifact["path"]] = artifact_path
            by_kind.setdefault(artifact["kind"], []).append(artifact_path)
        if stage["outcome"] != "NOT_DEMONSTRATED":
            require(stage.get("independently_observed_action") is True,
                    "PASS/FAIL needs an observed external/runtime action, not a configured flag")
            for key in ("action_description", "request_id", "provider_receipt_id"):
                require(nonempty(stage.get(key)), f"{key} is required for PASS/FAIL")
            require(by_kind.get("provider_receipt") and by_kind.get("runtime_observation"),
                    "PASS/FAIL requires provider_receipt and runtime_observation artifacts")
            require(set(by_kind["provider_receipt"]).isdisjoint(by_kind["runtime_observation"]),
                    "external and runtime observations must be separate artifacts")
            receipt = (environment["id"], run["provider_id"], stage["provider_receipt_id"])
            require(receipt not in seen_receipts, "duplicate/contradictory provider receipt")
            seen_receipts.add(receipt)
        if stage["outcome"] == "PASS":
            review = stage.get("acceptance_review", {})
            require(isinstance(review, dict) and nonempty(review.get("reviewed_by")) and
                    nonempty(review.get("reference")), "PASS requires operator acceptance review/reference")
            require(timestamp(review.get("reviewed_at")) <= completed,
                    "acceptance review cannot be after the run")
        if stage_id == "functional_action" and stage["outcome"] == "PASS":
            checks = stage.get("acceptance_checks", {})
            required_checks = workflow["functional_checks"]
            require(isinstance(checks, dict) and set(checks) == set(required_checks) and
                    all(value == "PASS" for value in checks.values()),
                    "functional PASS requires every workflow-specific acceptance check")
        if stage_id == "source_result_reconciliation" and stage["outcome"] == "PASS":
            diff = stage.get("reconciliation", {})
            for key, kind in (("source_artifact", "source_snapshot"),
                              ("result_artifact", "result_snapshot"),
                              ("diff_artifact", "reconciliation_report")):
                require(diff.get(key) in by_path and
                        by_path[diff[key]] in by_kind.get(kind, []),
                        f"reconciliation requires hashed {kind} artifact")
            source_path = by_path[diff["source_artifact"]]
            result_path = by_path[diff["result_artifact"]]
            require(source_path != result_path, "source and result snapshots must be separate files")
            diff_document = read_json(by_path[diff["diff_artifact"]])
            require(isinstance(diff_document, dict), "reconciliation report must be an object")
            source_document = read_json(source_path)
            result_document = read_json(result_path)
            require(isinstance(source_document, (dict, list)) and bool(source_document) and
                    json.dumps(source_document, sort_keys=True, separators=(",", ":")) ==
                    json.dumps(result_document, sort_keys=True, separators=(",", ":")),
                    "normalized source/result JSON snapshots differ or are empty")
            require(isinstance(diff_document.get("compared_fields"), list) and
                    bool(diff_document["compared_fields"]) and
                    all(nonempty(field) for field in diff_document["compared_fields"]),
                    "reconciliation report must identify compared fields")
            require(all(type(diff.get(k)) is int and diff[k] == 0 and
                        type(diff_document.get(k)) is int and diff_document[k] == 0
                        for k in DIFF_COUNTS),
                    "reconciliation PASS requires explicit zero missing/extra/changed counts in evidence and diff artifact")
    run["_evidence_path"] = path.relative_to(root).as_posix()
    return run


def summarize(registry, runs):
    rows = []
    for workflow in registry["workflows"]:
        matching = [r for r in runs if r["workflow_id"] == workflow["id"]]
        all_real = [r for r in matching if r["environment_class"] in REAL_CLASSES]
        all_real.sort(key=lambda r: (timestamp(r["completed_at"]), r["run_id"]))
        def context(run):
            return (run["environment"]["id"], run["environment"]["base_url"],
                    run["environment_class"], run["source"]["commit"], run["source"]["build_id"])
        selected = all_real[-1] if all_real else None
        real = [r for r in all_real if context(r) == context(selected)] if selected else []
        nonreal = [r for r in matching if r["environment_class"] in NONREAL_CLASSES]
        stages = []
        for stage_id in STAGES:
            observations = [(r, s) for r in real for s in r["stages"]
                            if s["stage_id"] == stage_id and s["outcome"] != "NOT_DEMONSTRATED"]
            observations.sort(key=lambda pair: (timestamp(pair[0]["completed_at"]), pair[0]["run_id"]))
            outcomes_by_time = {}
            for run, stage in observations:
                instant = timestamp(run["completed_at"])
                outcomes_by_time.setdefault(instant, set()).add(stage["outcome"])
            require(all(len(outcomes) == 1 for outcomes in outcomes_by_time.values()),
                    f"contradictory simultaneous outcomes for {workflow['id']}/{stage_id}")
            latest_run, latest_stage = observations[-1] if observations else (None, None)
            stages.append({
                "stage_id": stage_id,
                "status": latest_stage["outcome"] if latest_stage else "NOT_DEMONSTRATED",
                "real_system_credit": bool(latest_stage and latest_stage["outcome"] == "PASS"),
                "run_id": latest_run["run_id"] if latest_run else None,
                "environment_class": latest_run["environment_class"] if latest_run else None,
                "evidence_path": latest_run["_evidence_path"] if latest_run else None,
                "mock_fixture_passes": sum(s["outcome"] == "PASS" for r in nonreal
                                           for s in r["stages"] if s["stage_id"] == stage_id),
            })
        numerator = sum(s["real_system_credit"] for s in stages)
        counts = [r["vendor_attempt_count"] for r in matching]
        attempt_summary = {
            "known_count": sum(c for c in counts if c is not None),
            "unknown_runs": sum(c is None for c in counts),
            "status": "UNKNOWN" if not counts or any(c is None for c in counts) else "KNOWN",
        }
        rows.append({**workflow, "numerator": numerator, "denominator": len(STAGES),
                     "real_system_percentage": round(100 * numerator / len(STAGES), 2),
                     "evidence_state": "DEMONSTRATED" if numerator == len(STAGES) else
                         "PARTIALLY_DEMONSTRATED" if numerator else "NOT_DEMONSTRATED",
                     "real_system_classes": sorted({r["environment_class"] for r in real}),
                     "selected_evidence_context": {
                         "environment": selected["environment"], "environment_class": selected["environment_class"],
                         "source": selected["source"], "latest_completed_at": selected["completed_at"],
                     } if selected else None,
                     "other_context_run_ids": [r["run_id"] for r in all_real if context(r) != context(selected)],
                     "vendor_attempts": attempt_summary,
                     "mock_fixture_runs": len(nonreal), "stages": stages})
    return {
        "schema_version": 1, "method": "six_stage_observed_workflow_coverage",
        "not_a_success_probability": True,
        "scope": "Coverage of supplied, operator-reviewed evidence; no live network/provenance certification.",
        "workflows": rows, "file_workflows": registry.get("file_workflows", []),
        "accepted_run_ids": sorted(r["run_id"] for r in runs),
    }


def markdown(result):
    lines = ["# Integration evidence coverage", "",
             "Percentages count demonstrated stages in each customer workflow, not uptime, pass probability or vendor certification.",
             "All six stages remain in the denominator. Missing evidence means NOT_DEMONSTRATED, not failed.", "",
             "| Workflow | Scope | Real system stages | Coverage | Evidence class | Vendor attempts | Supplied mock/fixture runs |",
             "|---|---|---:|---:|---|---|---:|"]
    for row in result["workflows"]:
        attempts = row["vendor_attempts"]
        attempted = str(attempts["known_count"]) if attempts["status"] == "KNOWN" else (
            f"unknown ({attempts['known_count']} known; {attempts['unknown_runs']} unknown runs)")
        lines.append(f"| {row['label']} | {row['scope']} | {row['numerator']}/{row['denominator']} | "
                     f"{row['real_system_percentage']:.2f}% | {', '.join(row['real_system_classes']) or 'none supplied'} | "
                     f"{attempted} | {row['mock_fixture_runs']} |")
    lines += ["", "## Stage evidence", "",
              "| Workflow | Configuration/trust | Authentication/transport | Functional action | Reconciliation | Failure handling | Recovery/retry |",
              "|---|---|---|---|---|---|---|"]
    for row in result["workflows"]:
        lines.append("| " + " | ".join([row["label"]] + [s["status"] for s in row["stages"]]) + " |")
    lines += ["", "## Separate file workflows", "",
              "| Workflow | External connection coverage | Real-source reconciliation |",
              "|---|---|---|"]
    for row in result["file_workflows"]:
        lines.append(f"| {row['label']} | N/A | {row['real_source_reconciliation']} |")
    lines += ["", "A self-hosted Keycloak result applies only to the local Keycloak target. It cannot establish Okta, Entra or PingFederate readiness.",
              "Mock, fixture and simulator runs receive zero real-system credit. Raw receipts and tenant authorization still require human review.", ""]
    return "\n".join(lines)


def audit(registry_path, evidence_paths, artifact_root):
    registry = load_registry(Path(registry_path).resolve())
    root = Path(artifact_root).resolve()
    require(root.is_dir(), "artifact root must exist")
    runs, seen_runs, seen_receipts = [], set(), set()
    for path in sorted(Path(p).resolve() for p in evidence_paths):
        require(path.is_relative_to(root), "evidence document outside authorized root")
        runs.append(validate_run(path, registry, root, seen_runs, seen_receipts))
    return summarize(registry, runs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=str(Path(__file__).with_name("registry.json")))
    parser.add_argument("--evidence", nargs="*", default=[])
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-markdown", required=True)
    args = parser.parse_args(argv)
    try:
        result = audit(args.registry, args.evidence, args.artifact_root)
    except (EvidenceError, KeyError, TypeError) as exc:
        print(f"Evidence rejected; no report written: {exc}", file=sys.stderr)
        return 2
    for filename, content in ((args.output_json, json.dumps(result, indent=2, sort_keys=True) + "\n"),
                              (args.output_markdown, markdown(result))):
        path = Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(f"Validated {len(result['accepted_run_ids'])} runs across {len(result['workflows'])} workflows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
