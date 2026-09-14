"""Check MR routing without executing or trusting anything in its description."""

import json
import os
from pathlib import Path

WORK_PREFIXES = ("feat/", "fix/", "docs/", "test/", "security/")
LONG_LIVED = {"dev", "prod", "main"}


def allowed_route(base: str, head: str, same_repository: bool) -> bool:
    if base == "dev":
        if head == "main":
            return same_repository
        return head not in LONG_LIVED and head.startswith(WORK_PREFIXES)
    if base == "prod":
        return same_repository and head == "dev"
    if base == "main":
        return same_repository and head == "prod"
    return False


def main() -> int:
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        print("No MR routing check needed for this event.")
        return 0
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    pr = event["pull_request"]
    base, head = pr["base"], pr["head"]
    same_repository = base["repo"]["full_name"] == head["repo"]["full_name"]
    if not allowed_route(base["ref"], head["ref"], same_repository):
        print("Invalid MR route. Work targets dev; promotions follow dev to prod to main.")
        return 1
    print("MR route is valid. Milestone completion and review remain required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
