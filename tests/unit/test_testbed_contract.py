import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.artifacts import json_bytes
from src.testbed_backend import Backend
from src.testbed_contract import candidate_contract, verify_contract


class ContractTests(unittest.TestCase):
    def test_recorded_contract_matches_plans_without_certifying_readiness(self):
        record = verify_contract()
        self.assertEqual(record["contract_id"], "namespace-v1")
        self.assertEqual(len(record["sha256"]), 64)
        self.assertFalse(record["eligible_for_primary"])
        contract = candidate_contract()
        self.assertFalse(contract["host_interfaces_modified"])
        self.assertEqual(len(contract["policy_commands"]), 4)

    def test_command_changes_and_false_approval_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "contract.json"
            base = candidate_contract()
            for field, value in (
                ("schema_version", True),
                ("status", "accepted"),
                ("eligible_for_primary", True),
                ("topology_commands", []),
                ("policy_commands", {}),
            ):
                changed = copy.deepcopy(base)
                changed[field] = value
                path.write_bytes(json_bytes(changed))
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, "differs"):
                    verify_contract(path)
            path.write_bytes(b'{"schema_version":1,"schema_version":1}')
            with self.assertRaisesRegex(ValueError, "duplicate"):
                verify_contract(path)
            path.write_bytes(b" " * (65536 + 1))
            with self.assertRaisesRegex(ValueError, "exceeds"):
                verify_contract(path)

    def test_mutation_is_refused_before_namespace_ownership(self):
        with (
            patch("src.testbed_backend.require_linux"),
            patch("src.testbed_backend.verify_contract", side_effect=ValueError("drift")),
            patch("src.testbed_backend.OwnedTopology.create") as create,
        ):
            with self.assertRaisesRegex(ValueError, "drift"):
                Backend("namespace", "fifo", Path("unused")).setup()
            create.assert_not_called()

    def test_plan_change_is_detected_against_the_recorded_contract(self):
        with patch("src.testbed_contract.setup_commands", return_value=[]):
            with self.assertRaisesRegex(ValueError, "differs"):
                verify_contract()
