import copy
import unittest

from src.bulk import BulkPlan, client_command, server_command, summarize_bulk


def report(flows=1):
    return {
        "start": {
            "version": "iperf test fixture",
            "connected": [{"socket": i} for i in range(flows)],
            "test_start": {
                "protocol": "TCP",
                "num_streams": flows,
                "reverse": 1,
                "duration": 1,
                "omit": 0,
                "target_bitrate": 8_000_000 // flows,
            },
        },
        "end": {"streams": [{}] * flows, "sum_received": {"seconds": 1, "bytes": 1_000_000}},
        "intervals": [
            {
                "streams": [{}] * flows,
                "sum": {
                    "omitted": False,
                    "sender": False,
                    "start": 0,
                    "end": 1,
                    "bytes": 1_000_000,
                },
            }
        ],
    }


class BulkTests(unittest.TestCase):
    def test_aggregate_rate_is_split_without_multiplication(self):
        for rate in (50_000_000, 90_000_000, 110_000_000):
            plan = BulkPlan(rate, 8, 60, 10)
            self.assertEqual(plan.per_flow_bps * 8, rate)
            args = client_command(plan, "127.0.0.1", "127.0.0.1", 5201, linux=True)
            self.assertEqual(args[args.index("-b") + 1], str(rate // 8))
            self.assertEqual(args[-2:], ("-C", "cubic"))
        self.assertIn("--forceflush", server_command("127.0.0.1", 5201))

    def test_receiver_bytes_are_the_source_of_goodput(self):
        for flows in (1, 8):
            result = summarize_bulk(report(flows), BulkPlan(8_000_000, flows, 1))
            self.assertEqual(result["goodput_mbps"], 8)
            self.assertFalse(result["foreground_window_aligned"])

    def test_malformed_partial_and_wrong_sender_reports_fail(self):
        plan = BulkPlan(8_000_000, 1, 1)
        mutations = (
            ("start", "connected", []),
            ("start", "version", ""),
            ("end", "streams", []),
            ("end", "sum_received", {"seconds": 0, "bytes": 2}),
            ("end", "sum_received", {"seconds": 10, "bytes": 2}),
            ("end", "sum_received", {"seconds": 1, "bytes": True}),
        )
        for section, field, value in mutations:
            data = report()
            data[section][field] = value
            with self.assertRaises(ValueError):
                summarize_bulk(data, plan)
        for data in (None, {}, {"error": "connection refused"}):
            with self.assertRaises(ValueError):
                summarize_bulk(data, plan)
        for field, value in (("sender", True), ("omitted", 1), ("start", 0.5), ("end", 0)):
            data = report()
            data["intervals"][0]["sum"][field] = value
            with self.assertRaises(ValueError):
                summarize_bulk(data, plan)

    def test_warmup_omission_and_duplicate_flow_regressions(self):
        data = report()
        omitted = copy.deepcopy(data["intervals"][0])
        omitted["sum"]["omitted"] = True
        data["intervals"].insert(0, omitted)
        self.assertEqual(len(summarize_bulk(data, BulkPlan(8_000_000, 1, 1))["intervals"]), 1)
        data = report(8)
        data["start"]["connected"][-1]["socket"] = 0
        with self.assertRaises(ValueError):
            summarize_bulk(data, BulkPlan(8_000_000, 8, 1))

    def test_bounds_and_destinations(self):
        for args in ((10, 8, 1), (8, True, 1), (8, 2, 1), (8, 1, 0)):
            with self.assertRaises(ValueError):
                BulkPlan(*args)
        plan = BulkPlan(8_000_000, 1, 1)
        for address, port in (("8.8.8.8", 5201), ("0.0.0.0", 5201), ("127.0.0.1", 0)):
            with self.assertRaises(ValueError):
                client_command(plan, "127.0.0.1", address, port)
        with self.assertRaises(ValueError):
            server_command("127.0.0.1", 0)


if __name__ == "__main__":
    unittest.main()
