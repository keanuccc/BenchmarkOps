#!/usr/bin/env python3
"""BenchmarkOps CLI: run experiments, enforce regression gates, export reports,
apply industry packs, and test webhooks.

Usage:
  python bmops.py run <experiment_id> [--wait]
  python bmops.py check-regression --experiment <id> --baseline <file.json|0.90> [--threshold 0.05]
  python bmops.py export-report <report_id> [--format md|html|pdf] [--output out.md]
  python bmops.py pack apply <pack.json> [--project <name>]
  python bmops.py webhook test <webhook_id>

Configuration via environment:
  BENCHMARKOPS_API   default http://localhost:8000/api/v1
  BENCHMARKOPS_TOKEN optional Bearer token / organization API key
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = os.environ.get("BENCHMARKOPS_API", "http://localhost:8000/api/v1")
TOKEN = os.environ.get("BENCHMARKOPS_TOKEN", "")


def _headers(json_body: bool = True) -> dict:
    headers = {"User-Agent": "bmops-cli/1.0"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _request(method: str, path: str, body=None) -> dict | list:
    url = API_BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, headers=_headers(body is not None), method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"Cannot reach {url}: {e}") from e


def _cmd_run(args) -> None:
    result = _request("POST", f"/experiments/{args.experiment_id}/run")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.wait:
        return
    while True:
        exp = _request("GET", f"/experiments/{args.experiment_id}")
        if exp.get("status") in ("completed", "partial", "failed", "cancelled"):
            print(json.dumps(exp, ensure_ascii=False, indent=2))
            if exp.get("status") in ("failed", "cancelled"):
                sys.exit(1)
            return
        time.sleep(3)


def _cmd_check_regression(args) -> None:
    exp = _request("GET", f"/experiments/{args.experiment}")
    status = exp.get("status")
    if status not in ("completed", "partial"):
        raise SystemExit(f"Experiment {args.experiment} is {status!r}; run it first")
    current = float(exp.get("accuracy") or 0.0)

    baseline_path = Path(args.baseline)
    if baseline_path.exists():
        baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline = float(baseline_data.get("accuracy") or 0.0)
    else:
        baseline = float(args.baseline)
    threshold = float(args.threshold)

    print(
        f"accuracy={current:.4f} baseline={baseline:.4f} "
        f"threshold={threshold:.4f}"
    )
    if current < baseline - threshold:
        print(
            f"REGRESSION: accuracy dropped from {baseline:.4f} to {current:.4f} "
            f"(delta {- (current - baseline):.4f} > threshold {threshold:.4f})"
        )
        sys.exit(1)
    print("PASS: no regression detected")


def _cmd_export_report(args) -> None:
    suffix = "md" if args.format == "md" else args.format
    url = f"/reports/{args.report_id}/export"
    url += "" if args.format == "md" else f"?format={args.format}"
    if args.format == "pdf":
        url = f"/reports/{args.report_id}/export/pdf"
    req = urllib.request.Request(
        API_BASE + url, headers=_headers(json_body=False), method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            content = resp.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}") from e
    out = Path(args.output) if args.output else Path(f"report-{args.report_id}.{suffix}")
    out.write_bytes(content)
    print(f"saved {len(content)} bytes -> {out}")


def _cmd_pack_apply(args) -> None:
    pack = json.loads(Path(args.pack).read_text(encoding="utf-8"))
    project_name = args.project or pack.get("name", "行业评测包")
    project = _request(
        "POST",
        "/projects/",
        {
            "name": project_name,
            "description": pack.get("description", ""),
        },
    )
    pid = project["id"]
    print(f"project: {project_name} ({pid})")
    for bench in pack.get("benchmarks", []):
        created = _request(
            "POST",
            "/benchmarks/",
            {
                "project_id": pid,
                "name": bench["name"],
                "type": bench["type"],
                "metric": bench.get("metric"),
                "metric_config": bench.get("metric_config", {}),
                "description": bench.get("description"),
            },
        )
        print(f"  benchmark: {created['id']} ({created['name']})")
    for prompt in pack.get("prompts", []):
        created = _request(
            "POST",
            "/prompts/",
            {
                "project_id": pid,
                "name": prompt["name"],
                "template": prompt["template"],
                "description": prompt.get("description"),
            },
        )
        print(f"  prompt: {created['id']} ({created['name']})")
    print("done. Upload your dataset in the UI, then create experiments.")


def _cmd_webhook_test(args) -> None:
    result = _request("POST", f"/webhooks/{args.webhook_id}/test")
    print(json.dumps(result, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(prog="bmops")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="trigger an experiment run")
    run_p.add_argument("experiment_id")
    run_p.add_argument("--wait", action="store_true", help="poll until finished")
    run_p.set_defaults(func=_cmd_run)

    reg_p = sub.add_parser("check-regression", help="enforce an accuracy regression gate")
    reg_p.add_argument("--experiment", required=True)
    reg_p.add_argument("--baseline", required=True, help="baseline JSON file or accuracy float")
    reg_p.add_argument("--threshold", default="0.05", help="allowed drop before failing")
    reg_p.set_defaults(func=_cmd_check_regression)

    exp_p = sub.add_parser("export-report", help="export a report (md/html/pdf)")
    exp_p.add_argument("report_id")
    exp_p.add_argument("--format", default="md", choices=["md", "html", "pdf"])
    exp_p.add_argument("--output")
    exp_p.set_defaults(func=_cmd_export_report)

    pack_p = sub.add_parser("pack", help="apply an industry pack template")
    pack_sub = pack_p.add_subparsers(dest="pack_command", required=True)
    apply_p = pack_sub.add_parser("apply")
    apply_p.add_argument("pack", help="path to pack JSON")
    apply_p.add_argument("--project")
    apply_p.set_defaults(func=_cmd_pack_apply)

    hook_p = sub.add_parser("webhook", help="webhook utilities")
    hook_sub = hook_p.add_subparsers(dest="webhook_command", required=True)
    test_p = hook_sub.add_parser("test")
    test_p.add_argument("webhook_id")
    test_p.set_defaults(func=_cmd_webhook_test)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
