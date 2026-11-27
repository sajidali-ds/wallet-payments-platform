import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import loadtest_report  # noqa: E402


def trend(avg, med, p90, p95, p99, mx):
    return {"values": {"avg": avg, "med": med, "p(90)": p90, "p(95)": p95, "p(99)": p99, "max": mx}}


SUMMARY = {
    "meta": {
        "users": 50,
        "duration_seconds": 60,
        "transfer_rate": 50,
        "read_rate": 100,
        "login_rate": 2,
        "replay_ratio": 0.05,
    },
    "metrics": {
        "transfers_created": {"values": {"count": 3000}},
        "balance_reads_ok": {"values": {"count": 6000}},
        "logins_ok": {"values": {"count": 120}},
        "http_req_duration{flow:transfer}": trend(40.0, 35.0, 60.0, 80.5, 120.0, 400.0),
        "http_req_duration{flow:read}": trend(4.0, 3.0, 6.0, 9.0, 15.0, 90.0),
        "idempotency_replay_ok": {"values": {"rate": 1, "passes": 150, "fails": 0}},
        "checks": {"values": {"rate": 1.0}},
        "http_req_failed": {"values": {"rate": 0.0}},
        "dropped_iterations": {"values": {"count": 0}},
    },
}


class ReportTests(unittest.TestCase):
    def test_throughput_is_count_divided_by_duration(self):
        report = loadtest_report.build_report(SUMMARY)
        self.assertIn("| Transfers committed (replays excluded) | 3000 | 50.0 |", report)
        self.assertIn("| Balance reads | 6000 | 100.0 |", report)
        self.assertIn("| Logins | 120 | 2.0 |", report)

    def test_latency_row_lists_the_percentiles(self):
        report = loadtest_report.build_report(SUMMARY)
        self.assertIn("| POST /transfers | 40.0 | 35.0 | 60.0 | 80.5 | 120.0 | 400.0 |", report)

    def test_flows_without_data_are_left_out(self):
        report = loadtest_report.build_report(SUMMARY)
        latency_section = report.split("### Latency")[1].split("### Reliability")[0]
        self.assertNotIn("POST /auth/login |", latency_section)

    def test_reliability_section(self):
        report = loadtest_report.build_report(SUMMARY)
        self.assertIn("| Failed HTTP requests | 0.00% |", report)
        self.assertIn("100.00% (150 of 150)", report)
        self.assertIn("| Dropped iterations (system could not keep up) | 0 |", report)

    def test_environment_text_is_included(self):
        self.assertIn("t3.large", loadtest_report.build_report(SUMMARY, "t3.large"))

    def test_missing_metrics_and_zero_duration_do_not_crash(self):
        report = loadtest_report.build_report({"meta": {}, "metrics": {}})
        self.assertIn("n/a", report)

    def test_main_reads_a_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "summary.json"
            path.write_text(json.dumps(SUMMARY))
            self.assertEqual(loadtest_report.main([str(path)]), 0)

    def test_main_reports_a_missing_file(self):
        self.assertEqual(loadtest_report.main(["/nonexistent/summary.json"]), 1)


if __name__ == "__main__":
    unittest.main()
