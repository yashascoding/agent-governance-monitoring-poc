"""CLI entry point for the Agent Governance Monitoring POC.

Usage:
    python main.py demo [--mode normal|deadline|faulty|all] [--sns]
    python main.py watch [--pace 1.5]
    python main.py test
    python main.py report
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import console
from demo import (
    build_context,
    run_deadline_demo,
    run_faulty_demo,
    run_live_workload,
    run_normal_demo,
)
from governance.audit_report import build_audit_report
from governance.clock import SystemClock
from governance.event_store import JsonlEventStore
from governance.findings import FindingStore
from governance.monitor import MonitoringEngine
from governance.policy_loader import PolicyConfigError, load_policy_config
from notifications import LocalNotifier, SNSNotifier, sns_notifier_from_env

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_POLICY_PATH = REPO_ROOT / "config" / "policies.yaml"
DEMO_ROOT = REPO_ROOT / "reports" / "demo"
REPORT_PATH = REPO_ROOT / "reports" / "test_report.md"
WATCH_ROOT = REPO_ROOT / "reports" / "watch"

DEMO_MODES = ("normal", "deadline", "faulty")
DEMO_RUNNERS = {
    "normal": run_normal_demo,
    "deadline": run_deadline_demo,
    "faulty": run_faulty_demo,
}


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
    modes = list(DEMO_MODES) if args.mode == "all" else [args.mode]
    for mode in modes:
        ctx = build_context(DEMO_ROOT / mode, policy)
        if sns is not None:
            ctx.engine.notifiers["sns"] = sns
        result = DEMO_RUNNERS[mode](ctx)
        _print_summary(f"{mode.upper()} demo", ctx.notes, result, color=not args.no_color)
        exit_code |= _check_demo_expectations(mode, result)
    return exit_code


def _check_demo_expectations(mode: str, result) -> int:
    """Each demo asserts its own outcome; a violation means the POC regressed."""
    open_findings = [f for f in result.new_findings if f.status.value == "OPEN"]
    pending = [f for f in result.new_findings if f.status.value == "PENDING_INVESTIGATION"]
    if mode == "normal":
        if open_findings:
            print("UNEXPECTED: normal demo produced OPEN findings", file=sys.stderr)
            return 1
    elif mode == "faulty":
        if not result.new_findings:
            print("UNEXPECTED: faulty demo produced no findings", file=sys.stderr)
            return 1
    elif mode == "deadline":
        if not pending:
            print(
                "UNEXPECTED: the stalled workflow was not held as PENDING_INVESTIGATION",
                file=sys.stderr,
            )
            return 1
        if not open_findings:
            print(
                "UNEXPECTED: the expired workflow did not escalate to a violation",
                file=sys.stderr,
            )
            return 1
    return 0


def _print_summary(title: str, notes: list[str], result, color: bool = True) -> None:
    print(f"\n=== {title} ===")
    for note in notes:
        print(f"  - {note}")
    print(f"  events processed: {result.processed_events}")
    print(f"  new findings:     {len(result.new_findings)}")
    print(f"  suppressed dupes: {len(result.suppressed_duplicates)}")
    print(f"  alert deliveries: {len(result.deliveries)}")
    for finding in result.new_findings:
        sev = console.severity(f"[{finding.severity.value}/{finding.status.value}]", enabled=color)
        print(f"    {sev} {finding.rule_id} task={finding.task_id}: {finding.observed_behaviour}")
    for delivery in result.deliveries:
        status = delivery.status
        if color:
            status = console.style(
                status,
                console.GREEN if delivery.status == "SUCCESS" else console.RED,
            )
        print(f"    delivery {delivery.backend}: {status} ({delivery.detail})")


def cmd_watch(args: argparse.Namespace) -> int:
    """Run the agents and the independent monitor side by side, live."""
    policy = _load_policy_or_exit(args.policy)
    color = not args.no_color

    root = args.out
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    store = JsonlEventStore(root / "events.jsonl", run_id="watch-run")
    finding_store = FindingStore(root / "findings.jsonl")
    notifier = LocalNotifier(root / "alerts.jsonl", echo=True, color=color)
    engine = MonitoringEngine(
        policy, finding_store, notifiers=[notifier], clock=SystemClock()
    )

    stop = threading.Event()
    print(f"{console.bold('LIVE MONITOR', enabled=color)} - policy v{policy.version}")
    print(f"  event log : {store.path}")
    print(f"  findings  : {finding_store.path}")
    print(f"  alerts    : {notifier.alerts_path}")
    print("  agents are emitting events; findings appear below as they are detected.")
    print("")

    def announce(label: str) -> None:
        print(f"{console.dim('->', enabled=color)} {label}", flush=True)

    worker = threading.Thread(
        target=run_live_workload,
        kwargs={
            "policy": policy,
            "store": store,
            "clock": SystemClock(),
            "pace": args.pace,
            "on_step": announce,
            "stop": stop,
        },
        daemon=True,
    )
    worker.start()

    seen = 0
    findings_raised = 0
    alerts_emitted = 0
    processed_total = 0
    last_change = time.monotonic()
    try:
        while worker.is_alive():
            raw = store.read_all()
            total = raw.report.valid_events
            seen = total
            if total != processed_total:
                last_change = time.monotonic()
            # Debounce: only evaluate once the event stream has been quiet for
            # a moment, so one logical agent action is judged as a whole rather
            # than being caught mid-step.
            if total > processed_total and (time.monotonic() - last_change) >= args.quiet:
                result = engine.process_events(raw.events[processed_total:])
                processed_total = total
                findings_raised += len(result.new_findings)
                alerts_emitted += len(result.deliveries)
                print(
                    console.dim(
                        f"   ... {total} event(s) processed, "
                        f"{findings_raised} finding(s) so far",
                        enabled=color,
                    ),
                    flush=True,
                )
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("")
        stop.set()
        worker.join(timeout=2)

    final = engine.process_events(store.read_all().events[processed_total:])
    findings_raised += len(final.new_findings)
    alerts_emitted += len(final.deliveries)
    seen = max(seen, store.read_all().report.valid_events)
    print("")
    print(f"{console.bold('SUMMARY', enabled=color)}")
    print(f"  events processed: {seen}")
    print(f"  findings raised:  {findings_raised}")
    print(f"  alerts emitted:   {alerts_emitted}")
    print(f"  findings file:    {finding_store.path}")
    print(f"  alerts file:      {notifier.alerts_path}")
    return 0


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

    demo = sub.add_parser("demo", help="run demo scenarios (normal, deadline and/or faulty)")
    demo.add_argument("--mode", choices=[*DEMO_MODES, "all"], default="all")
    demo.add_argument("--sns", action="store_true", help="also publish alerts to SNS (needs SNS_TOPIC_ARN)")
    demo.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    demo.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    demo.set_defaults(func=cmd_demo)

    watch = sub.add_parser(
        "watch", help="run the agents and the independent monitor live, side by side"
    )
    watch.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    watch.add_argument("--out", type=Path, default=WATCH_ROOT)
    watch.add_argument(
        "--pace", type=float, default=1.5, help="seconds between agent steps"
    )
    watch.add_argument(
        "--interval", type=float, default=0.1, help="seconds between monitor polls"
    )
    watch.add_argument(
        "--quiet",
        type=float,
        default=0.6,
        help="seconds of event-stream silence before a batch is evaluated",
    )
    watch.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    watch.set_defaults(func=cmd_watch)

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
