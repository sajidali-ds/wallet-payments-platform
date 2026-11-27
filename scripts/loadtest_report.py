import argparse
import json
import sys
from pathlib import Path

LATENCY_FLOWS = [
    ("transfer", "POST /transfers"),
    ("read", "GET /wallets/me/balance"),
    ("login", "POST /auth/login"),
    ("replay", "POST /transfers (idempotent replay)"),
]


def _values(metrics: dict, name: str) -> dict:
    return metrics.get(name, {}).get("values", {})


def _count(metrics: dict, name: str) -> float:
    return _values(metrics, name).get("count", 0) or 0


def _fmt(value, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _percent(value) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def build_report(summary: dict, environment: str = "") -> str:
    meta = summary.get("meta", {})
    metrics = summary.get("metrics", {})
    duration = float(meta.get("duration_seconds") or 0)

    def per_second(count: float) -> str:
        return _fmt(count / duration) if duration else "n/a"

    lines = ["## Load test results", ""]
    lines += ["| Setting | Value |", "|---|---|"]
    lines += [
        f"| Environment | {environment or '(fill in: instance type, where k6 ran)'} |",
        f"| Users (wallets) | {meta.get('users', 'n/a')} |",
        f"| Duration | {meta.get('duration_seconds', 'n/a')} s |",
        f"| Target rates | {meta.get('transfer_rate', 'n/a')} transfers/s, "
        f"{meta.get('read_rate', 'n/a')} reads/s, {meta.get('login_rate', 'n/a')} logins/s |",
        f"| Idempotent replay share | {meta.get('replay_ratio', 'n/a')} |",
        "",
    ]

    lines += ["### Throughput", "", "| Flow | Completed | Per second |", "|---|---|---|"]
    for label, metric in (
        ("Transfers committed (replays excluded)", "transfers_created"),
        ("Balance reads", "balance_reads_ok"),
        ("Logins", "logins_ok"),
    ):
        count = _count(metrics, metric)
        lines.append(f"| {label} | {int(count)} | {per_second(count)} |")
    lines.append("")

    lines += [
        "### Latency (ms)",
        "",
        "| Request | avg | p50 | p90 | p95 | p99 | max |",
        "|---|---|---|---|---|---|---|",
    ]
    for flow, label in LATENCY_FLOWS:
        v = _values(metrics, f"http_req_duration{{flow:{flow}}}")
        if not v:
            continue
        cells = [v.get(k) for k in ("avg", "med", "p(90)", "p(95)", "p(99)", "max")]
        lines.append(f"| {label} | " + " | ".join(_fmt(c) for c in cells) + " |")
    lines.append("")

    replay = _values(metrics, "idempotency_replay_ok")
    checks = _values(metrics, "checks")
    failed = _values(metrics, "http_req_failed")
    lines += ["### Reliability", "", "| Measure | Value |", "|---|---|"]
    lines += [
        f"| Failed HTTP requests | {_percent(failed.get('rate'))} |",
        f"| Checks passed | {_percent(checks.get('rate'))} |",
        f"| Idempotent replays answered from the stored response | "
        f"{_percent(replay.get('rate'))} ({int(replay.get('passes', 0))} of "
        f"{int(replay.get('passes', 0) + replay.get('fails', 0))}) |",
        "| Dropped iterations (system could not keep up) | "
        f"{int(_count(metrics, 'dropped_iterations'))} |",
        "",
    ]
    lines += [
        "_Consistency after the run: paste the output of `make verify` here._",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="loadtests/results/summary.json")
    parser.add_argument("--environment", default="")
    args = parser.parse_args(argv)
    path = Path(args.path)
    if not path.exists():
        print(f"{path} not found: run `make loadtest` first", file=sys.stderr)
        return 1
    print(build_report(json.loads(path.read_text()), args.environment))
    return 0


if __name__ == "__main__":
    sys.exit(main())
