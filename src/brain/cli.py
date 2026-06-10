from __future__ import annotations

import argparse
from pathlib import Path

from .git import GitError, find_repositories, repository_status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brain", description="Manage Git repositories.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Show Git status for a repository.")
    status_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        type=Path,
        help="Repository path. Defaults to the current directory.",
    )

    repos_parser = subparsers.add_parser("repos", help="Find Git repositories below a path.")
    repos_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        type=Path,
        help="Search root. Defaults to the current directory.",
    )
    repos_parser.add_argument(
        "--max-depth",
        type=int,
        default=4,
        help="Maximum directory depth to search. Defaults to 4.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "status":
            status = repository_status(args.path)
            print(f"path: {status.path}")
            print(f"branch: {status.branch}")
            if status.changes:
                print("changes:")
                for change in status.changes:
                    print(f"  {change}")
            else:
                print("changes: clean")
            return 0

        if args.command == "repos":
            repositories = find_repositories(args.path, max_depth=args.max_depth)
            for repo in repositories:
                print(repo)
            return 0
    except GitError as exc:
        parser.exit(2, f"brain: {exc}\n")

    parser.error(f"unknown command: {args.command}")
    return 2
