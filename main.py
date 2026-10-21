"""CLI entry point for the Agent Governance Monitoring POC.

Usage:
    python main.py demo [--mode normal|faulty|all] [--sns]
    python main.py test
    python main.py report
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from demo import build_context, run_faulty_demo, run_normal_demo
from governance.audit_report import build_audit_report
from governance.policy_loader import PolicyConfigError, load_policy_config
from notifications import SNSNotifier, sns_notifier_from_env

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_POLICY_PATH = REPO_ROOT / "config" / "policies.yaml"
DEMO_ROOT = REPO_ROOT / "reports" / "demo"
REPORT_PATH = REPO_ROOT / "reports" / "test_report.md"


def _load_policy_or_exit(path: Path):
    try:
        return load_policy_config(path)
    except PolicyConfigError as exc:
        print(f"FATAL: invalid policy configuration: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def cmd_demo(args: argparse.Namespace) -> int:
    policy = _load_policy_or_exit(args.policy)
    sns: SNSNotifier | None = None
    if args.sns:
        sns = sns_notifier_from_env()
        if sns is None:
            print(
                "WARNING: --sns requested but SNS_TOPIC_ARN is not set; "
                "running with the local backend only",
                file=sys.stderr,
            )

    exit_code = 0
    if args.mode in ("normal", "all"):
        ctx = build_context(DEMO_ROOT / "normal", policy)
        if sns is not None:
            ctx.engine.notifiers["sns"] = sns
        result = run_normal_demo(ctx)
        _print_summary("NORMAL demo", ctx.notes, result)
        open_findings = [f for f in result.new_findings if f.status.value == "OPEN"]
        if open_findings:
            print("UNEXPECTED: normal demo produced OPEN findings", file=sys.stderr)
            exit_code = 1
    if args.mode in ("faulty", "all"):
        ctx = build_context(DEMO_ROOT / "faulty", policy)
        if sns is not None:
            ctx.engine.notifiers["sns"] = sns
        result = run_faulty_demo(ctx)
        _print_summary("FAULTY demo", ctx.notes, result)
        if not result.new_findings:
            print("UNEXPECTED: faulty demo produced no findings", file=sys.stderr)
            exit_code = 1
    return exit_code


def _print_summary(title: str, notes: list[str], result) -> None:
    print(f"\n=== {title} ===")
    for note in notes:
        print(f"  - {note}")
    print(f"  events processed: {result.processed_events}")
    print(f"  new findings:     {len(result.new_findings)}")
    print(f"  suppressed dupes: {len(result.suppressed_duplicates)}")
    print(f"  alert deliveries: {len(result.deliveries)}")
    for finding in result.new_findings:
        print(
            f"    [{finding.severity.value}/{finding.status.value}] "
            f"{finding.rule_id} task={finding.task_id}: {finding.observed_behaviour}"
        )
    for delivery in result.deliveries:
        print(
            f"    delivery {delivery.backend}: {delivery.status} "
            f"({delivery.detail})"
        )


def cmd_test(_args: argparse.Namespace) -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(REPO_ROOT / "tests")],
        cwd=REPO_ROOT,
    )
    if REPORT_PATH.exists():
        print(f"\nTest report: {REPORT_PATH}")
        print(REPORT_PATH.read_text(encoding="utf-8"))
    return proc.returncode


def cmd_report(args: argparse.Namespace) -> int:
    if args.audit is not None:
        findings_path = args.audit / "findings.jsonl"
        alerts_path = args.audit / "alerts.jsonl"
        if not findings_path.exists():
            print(f"No findings file at {findings_path}. Run a demo first.", file=sys.stderr)
            return 1
        report = build_audit_report(args.audit.name, findings_path, alerts_path)
        print(report)
        out = REPO_ROOT / "reports" / f"audit_{args.audit.name}.md"
        out.write_text(report, encoding="utf-8")
        print(f"Audit report written to {out}")
        return 0
    if not REPORT_PATH.exists():
        print("No test report found. Run `python main.py test` first.", file=sys.stderr)
        return 1
    print(REPORT_PATH.read_text(encoding="utf-8"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-governance-poc",
        description="Agent governance & monitoring POC CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="run demo scenarios (normal and/or faulty)")
    demo.add_argument("--mode", choices=["normal", "faulty", "all"], default="all")
    demo.add_argument("--sns", action="store_true", help="also publish alerts to SNS (needs SNS_TOPIC_ARN)")
    demo.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    demo.set_defaults(func=cmd_demo)

    test = sub.add_parser("test", help="run the full pytest suite and print the report")
    test.set_defaults(func=cmd_test)

    report = sub.add_parser("report", help="print the last generated test report, or build an audit report")
    report.add_argument(
        "--audit",
        type=Path,
        default=None,
        help="build a markdown audit report from a demo output dir (e.g. reports/demo/faulty)",
    )
    report.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
