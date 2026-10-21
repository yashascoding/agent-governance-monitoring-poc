# Agent Governance & Monitoring POC

A small, testable proof of concept showing how to monitor autonomous AI agents
for policy violations. It builds a multi-agent system with a loan-processing
agent, a task-execution agent, and a data-access agent, then independently
monitors their structured event logs for policy breaches and raises alerts.

This is a **POC**, not a production system. It uses synthetic data only and
never executes real financial transactions or touches real restricted data.

## Architecture

```
Task Agents → Structured Event Log → Independent Monitoring Engine
            → Policy Violation Findings → Alerting System → Audit Report
```

- **Task agents** emit structured events (JSON Lines) and enforce policy at
  their own boundaries.
- **The monitoring engine** does *not* trust an agent's self-reported
  conclusion. It re-derives amounts, durations, authorization state, and
  permissions from the raw events + corroborating metadata using deterministic
  Python rules.
- **Detectors** implement the required rules (missing authorization,
  unauthorized approval/read, short task duration, out-of-order/inconsistent
  events).
- **Findings** carry supporting event IDs, severity, expected vs observed
  behaviour, and a recommended response.
- **Alerting** supports a local JSONL+terminal backend (works offline) and an
  Amazon SNS backend (boto3).
- **Reports**: a real test report is generated from pytest execution; audit
  reports summarise findings and delivery outcomes.

## Project layout

```
agents/            loan_agent.py, task_agent.py, data_agent.py
governance/        policy_loader.py, event_schema.py, event_store.py,
                   detectors.py, findings.py, monitor.py, clock.py,
                   audit_report.py, cloudtrail.py
notifications/     base.py, local_notifier.py, sns_notifier.py
config/            policies.yaml   (single source of truth)
tests/             unit/, integration/, scenarios/
reports/           generated test + audit reports
main.py            CLI entry point
demo.py            demo scenario runners
```

## Setup

Requires Python 3.11+ (developed on 3.12).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` only if you plan to use SNS. The local backend
needs no credentials.

## Run the demo

```bash
# Normal (compliant) and faulty (violation) scenarios
python main.py demo

# Only one mode
python main.py demo --mode normal
python main.py demo --mode faulty

# Also publish alerts to SNS (requires SNS_TOPIC_ARN)
python main.py demo --mode faulty --sns
```

The faulty demo shows the enforcement boundary *blocking* the unauthorized
approval/data read, while the independent monitor still *detects* the attempt.
It also runs isolated legacy-bug simulations that record unauthorized outcomes.

Outputs are written under `reports/demo/{normal,faulty}/`:
- `events.jsonl` – raw structured events
- `findings.jsonl` – monitor findings
- `alerts.jsonl` – local alert records

## Run the tests and generate the report

```bash
python main.py test          # runs pytest, then prints reports/test_report.md
python main.py report        # print the last test report
python main.py report --audit reports/demo/faulty   # build an audit report
```

## The policies

All policy lives in `config/policies.yaml` and is validated at startup;
invalid config fails safely with a clear error. Nothing is hardcoded in agents.

- **Loan**: `< INR 1,000` may be auto-approved; `>= INR 1,000` requires recorded
  human authorization before approval can be finalized.
- **Task**: baseline duration 300s; durations below 60s are anomalies
  (investigation signals, not proof of malice).
- **Data access**: `loan-agent → loan_applications`, `task-agent → task_records`,
  `data-agent → public_test_data`.
- **Monitoring**: incomplete loan workflows are "pending" until a deadline
  (600s) expires — a missing event is not automatically treated as a violation.
- **Alerts**: CRITICAL/HIGH route to local+SNS, MEDIUM/LOW to local.

## Detectors

| Rule ID | Detects |
|---|---|
| RULE-LOAN-001 | Missing human authorization at/above threshold (attempt, or expired workflow) |
| RULE-LOAN-002 | Final approval inconsistent with authorization state (incl. explicit denial) |
| RULE-TASK-001 | Implausibly short task duration (corroborated via timestamps) |
| RULE-DATA-001 | Unauthorized data-access attempt (denied at the boundary) |
| RULE-DATA-002 | Successful unauthorized data read (legacy-bug style) |
| RULE-SEQ-001 | Out-of-order events |
| RULE-SEQ-002 | Inconsistent/missing-prerequisite events, conflicting final outcomes |

## Duplicate handling

Findings have a deterministic content key (rule + agent + task + status +
evidence signature). Reprocessing the same events produces no duplicate
findings or alerts; duplicate event IDs in the log are ignored (first wins).
The event reader also tolerates malformed records (skipped and counted).

## Acceptance scenarios (T1–T12)

T1 auto-approved ₹800 · T2 authorized ₹1,500 · T3 bypass attempt (critical) ·
T4 legacy unauthorized approval (critical) · T5 normal duration · T6 10s
duration anomaly · T7 restricted access attempt · T8 legacy successful
restricted read (high) · T9 duplicate events (no duplicate finding) · T10
incomplete workflow (pending, not accused) · T11 malformed events/invalid
config · T12 all-valid no false positives.

## Amazon SNS

See `docs/SNS_SETUP.md`. SNS publish success means the API accepted the request,
**not** that an email was delivered.

## Optional CloudTrail extension

`governance/cloudtrail.py` can read *management* events with a read-only,
least-privilege identity. CloudTrail does not capture this POC's
application-specific events (those are logged by the app), and *data* events
(e.g. S3 object reads) require separate, potentially billable configuration.

## Security notes

- Synthetic data only; no real transactions or restricted resources.
- No secrets in logs; the event schema rejects sensitive-looking evidence keys.
- Never commit `.env` or AWS credentials (see `.gitignore`).
- Passing tests does not make this production-ready: there is no authn/authz,
  no tamper-evident log storage, no HA, and enforcement is in-process.
