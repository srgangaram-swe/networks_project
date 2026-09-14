import unittest

from scripts.branch_policy import allowed_route


class BranchPolicyTests(unittest.TestCase):
    def test_work_branches_target_dev(self):
        for prefix in ("feat", "fix", "docs", "test", "security"):
            self.assertTrue(allowed_route("dev", f"{prefix}/12-work", True))
            self.assertTrue(allowed_route("dev", f"{prefix}/12-work", False))

    def test_only_forward_promotions(self):
        self.assertTrue(allowed_route("prod", "dev", True))
        self.assertTrue(allowed_route("main", "prod", True))
        self.assertFalse(allowed_route("main", "dev", True))
        self.assertFalse(allowed_route("prod", "main", True))
        self.assertFalse(allowed_route("prod", "feat/12-work", True))
        self.assertFalse(allowed_route("main", "feat/12-work", True))

    def test_rejects_fork_promotions(self):
        self.assertFalse(allowed_route("prod", "dev", False))
        self.assertFalse(allowed_route("main", "prod", False))

    def test_only_same_repository_release_ancestry_sync(self):
        self.assertTrue(allowed_route("dev", "main", True))
        self.assertFalse(allowed_route("dev", "main", False))
        self.assertFalse(allowed_route("dev", "prod", True))

    def test_unknown_or_self_route_rejected(self):
        self.assertFalse(allowed_route("unknown", "feat/12-work", True))
        self.assertFalse(allowed_route("dev", "dev", True))
        self.assertFalse(allowed_route("dev", "unstructured", True))
