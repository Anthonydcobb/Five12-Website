#!/usr/bin/env python3
import os
import argparse

def parse_args():
    parser = argparse.ArgumentParser(
        description="Print directory tree, collapsing specified directories and ignoring .pyc files"
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Root directory to start from (default: current directory)",
    )
    parser.add_argument(
        "-s",
        "--skip",
        nargs="*",
        default=[
            "node_modules",
            ".git",
            "venv",
            ".venv",
            "werkzeug",
            "Lib",
            "migrations"
        ],
        help="Directory names to collapse (print but not traverse); case-insensitive",
    )
    return parser.parse_args()

def print_tree(current_path, prefix, skip_dirs_lower):
    try:
        entries = sorted(os.listdir(current_path))
    except PermissionError:
        return

    for idx, name in enumerate(entries):
        path = os.path.join(current_path, name)
        is_last = idx == len(entries) - 1
        connector = "└── " if is_last else "├── "

        # Skip any .pyc files
        if os.path.isfile(path) and name.endswith(".pyc"):
            continue

        if os.path.isdir(path):
            print(prefix + connector + name + "/")
            # Don't descend into skipped dirs
            if name.lower() in skip_dirs_lower:
                continue
            extension = "    " if is_last else "│   "
            print_tree(path, prefix + extension, skip_dirs_lower)
        else:
            print(prefix + connector + name)

if __name__ == "__main__":
    args = parse_args()
    # Normalize skip-list to lowercase, strip any trailing slashes
    skip_dirs_lower = {d.rstrip("/\\").lower() for d in args.skip}

    root = os.path.abspath(args.root)
    print(os.path.basename(root) + "/")
    print_tree(root, "", skip_dirs_lower)
