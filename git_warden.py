#!/usr/bin/env python3
"""Git hook manager and branch policy enforcer. Install pre-commit checks,
validate branch names, enforce commit message formats. Zero deps."""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from typing import Any


DEFAULT_CONFIG = """# .gitwarden.yaml — Git Warden configuration
# https://github.com/realMNohgee/Git_Warden

branch:
  # Regex pattern for valid branch names
  pattern: "^(feature|fix|chore|docs|test|refactor)/[a-z0-9._-]+$"

commit:
  # Regex pattern for valid commit messages (first line only)
  pattern: "^(feat|fix|chore|docs|test|refactor|style|perf|ci|build|revert): "

files:
  max_size_mb: 5
  block_patterns:
    # Common secret patterns — checked case-insensitively on diff content
    - "-----BEGIN RSA PRIVATE KEY-----"
    - "-----BEGIN OPENSSH PRIVATE KEY-----"
    - "-----BEGIN EC PRIVATE KEY-----"
    - "-----BEGIN PGP PRIVATE KEY BLOCK-----"
    - "api_key\\s*=\\s*['\\\"][A-Za-z0-9_-]{20,}['\\\"]"
    - "password\\s*=\\s*['\\\"][^'\\\"]+['\\\"]"
    - "secret\\s*=\\s*['\\\"][^'\\\"]+['\\\"]"
"""

HOOK_TEMPLATES: dict[str, str] = {
    "pre-commit": """#!/bin/bash
# Git Warden pre-commit hook
python3 {warden_path} check --no-bypass
exit $?
""",
    "commit-msg": """#!/bin/bash
# Git Warden commit-msg hook
python3 {warden_path} check-msg "$1"
exit $?
""",
    "pre-push": """#!/bin/bash
# Git Warden pre-push hook
python3 {warden_path} check --no-bypass
exit $?
""",
}


def _find_git_root(path: str | None = None) -> str | None:
    """Find the root of a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, cwd=path,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def _find_warden_path() -> str:
    """Find the absolute path to this script."""
    return os.path.abspath(sys.argv[0])


def _parse_config(config_path: str) -> dict[str, Any]:
    """Parse .gitwarden.yaml. Minimal YAML parser for our simple config."""
    config: dict[str, Any] = {
        "branch": {"pattern": r"^(feature|fix|chore|docs|test|refactor)/[a-z0-9._-]+$"},
        "commit": {"pattern": r"^(feat|fix|chore|docs|test|refactor|style|perf|ci|build|revert): "},
        "files": {"max_size_mb": 5, "block_patterns": []},
    }
    if not os.path.exists(config_path):
        return config

    with open(config_path) as f:
        content = f.read()

    # Parse with simple indentation-based approach
    current_section: str | None = None
    current_key: str | None = None
    in_list: bool = False
    list_items: list[str] = []

    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())

        if indent == 0 and stripped.endswith(":"):
            current_section = stripped[:-1]
            current_key = None
            in_list = False
            if current_section not in config:
                config[current_section] = {}
            continue

        if current_section:
            if stripped.startswith("- "):
                in_list = True
                item = stripped[2:].strip().strip("'\"")
                list_items.append(item)
                continue
            elif ":" in stripped and not stripped.startswith("-"):
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip().strip("'\"")
                if current_section not in config:
                    config[current_section] = {}
                config[current_section][key] = val
                current_key = key
                in_list = False

    if list_items and current_section and current_key:
        config[current_section][current_key] = list_items

    return config


def _get_current_branch(git_root: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=git_root, timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except subprocess.SubprocessError:
        return None


def _check_branch(config: dict, git_root: str) -> list[dict]:
    branch = _get_current_branch(git_root)
    results: list[dict] = []
    if not branch:
        return [{"check": "branch_name", "status": "error", "message": "Could not detect branch"}]

    pattern = config.get("branch", {}).get("pattern", "")
    if pattern and not re.match(pattern, branch):
        results.append({
            "check": "branch_name",
            "status": "fail",
            "branch": branch,
            "pattern": pattern,
            "message": f"Branch '{branch}' does not match pattern '{pattern}'",
        })
    else:
        results.append({
            "check": "branch_name",
            "status": "pass",
            "branch": branch,
        })
    return results


def _check_commit_msg(config: dict, msg: str) -> list[dict]:
    results: list[dict] = []
    first_line = msg.split("\n")[0].strip()

    # Skip merge commits
    if first_line.startswith("Merge "):
        return [{"check": "commit_message", "status": "pass", "message": "Merge commit, skipping"}]

    pattern = config.get("commit", {}).get("pattern", "")
    if pattern and not re.match(pattern, first_line):
        results.append({
            "check": "commit_message",
            "status": "fail",
            "message": first_line[:80],
            "pattern": pattern,
            "detail": f"Commit message does not match '{pattern}'",
        })
    else:
        results.append({
            "check": "commit_message",
            "status": "pass",
            "message": first_line[:80],
        })
    return results


def _check_secrets(config: dict, git_root: str) -> list[dict]:
    results: list[dict] = []
    block_patterns = config.get("files", {}).get("block_patterns", [])

    if not block_patterns:
        return results

    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, cwd=git_root, timeout=30,
        )
        if result.returncode != 0:
            return results
        staged_files = [f for f in result.stdout.strip().split("\n") if f]

        for fpath in staged_files:
            full_path = os.path.join(git_root, fpath)
            if not os.path.isfile(full_path):
                continue
            try:
                with open(full_path, errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue

            for pattern_str in block_patterns:
                try:
                    if re.search(pattern_str, content, re.IGNORECASE):
                        results.append({
                            "check": "secrets",
                            "status": "fail",
                            "file": fpath,
                            "pattern": pattern_str,
                            "message": f"Potential secret detected in {fpath}",
                        })
                except re.error:
                    pass
    except (subprocess.SubprocessError, OSError):
        pass

    if not results:
        results.append({"check": "secrets", "status": "pass"})
    return results


def _check_file_sizes(config: dict, git_root: str) -> list[dict]:
    results: list[dict] = []
    max_mb = config.get("files", {}).get("max_size_mb", 5)
    if isinstance(max_mb, str):
        try:
            max_mb = int(max_mb)
        except ValueError:
            max_mb = 5
    max_bytes = int(max_mb) * 1024 * 1024

    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, cwd=git_root, timeout=30,
        )
        if result.returncode != 0:
            return results
        staged_files = [f for f in result.stdout.strip().split("\n") if f]

        for fpath in staged_files:
            full_path = os.path.join(git_root, fpath)
            if not os.path.isfile(full_path):
                continue
            try:
                size = os.path.getsize(full_path)
            except OSError:
                continue
            if size > max_bytes:
                results.append({
                    "check": "file_size",
                    "status": "fail",
                    "file": fpath,
                    "size_mb": round(size / (1024 * 1024), 2),
                    "limit_mb": max_mb,
                    "message": f"{fpath} is {size / (1024 * 1024):.1f}MB (limit: {max_mb}MB)",
                })
    except (subprocess.SubprocessError, OSError):
        pass

    if not results:
        results.append({"check": "file_size", "status": "pass"})
    return results


# ── Subcommand Handlers ──────────────────────────────────────────────────────


def cmd_install(args: argparse.Namespace) -> int:
    hooks_dir = args.hooks_dir
    hooks_to_install = args.hooks
    git_root = _find_git_root()

    if not git_root:
        print("Error: not inside a git repository.", file=sys.stderr)
        return 1

    hooks_dir_full = os.path.join(git_root, hooks_dir)
    os.makedirs(hooks_dir_full, exist_ok=True)

    warden_path = _find_warden_path()
    all_hooks = ["pre-commit", "commit-msg", "pre-push"]

    if hooks_to_install == "all":
        selected = all_hooks
    else:
        selected = [h.strip() for h in hooks_to_install.split(",")]

    installed = []
    skipped = []

    for hook_name in selected:
        if hook_name not in all_hooks:
            if args.format == "text":
                print(f"Unknown hook: {hook_name}")
            skipped.append(hook_name)
            continue

        hook_path = os.path.join(hooks_dir_full, hook_name)
        template = HOOK_TEMPLATES.get(hook_name, "")
        content = template.format(warden_path=warden_path)

        with open(hook_path, "w") as f:
            f.write(content)
        os.chmod(hook_path, os.stat(hook_path).st_mode | stat.S_IEXEC)
        installed.append(hook_name)

    if args.format == "json":
        print(json.dumps({
            "repo": git_root,
            "hooks_dir": hooks_dir_full,
            "installed": installed,
            "skipped": skipped,
        }, indent=2))
    else:
        print(f"🔐 Git Warden — hooks installed in {git_root}")
        for h in installed:
            print(f"  ✅ {h}")
        for h in skipped:
            print(f"  ⚠️  {h} (unknown)")

    return 0 if not skipped else 0


def cmd_check(args: argparse.Namespace) -> int:
    git_root = _find_git_root()
    if not git_root:
        print("Error: not inside a git repository.", file=sys.stderr)
        return 1

    config_path = os.path.join(git_root, ".gitwarden.yaml")
    config = _parse_config(config_path)

    all_results: list[dict] = []

    # Branch check
    all_results.extend(_check_branch(config, git_root))

    # Secrets check
    all_results.extend(_check_secrets(config, git_root))

    # File size check
    all_results.extend(_check_file_sizes(config, git_root))

    failures = [r for r in all_results if r.get("status") == "fail"]
    errors = [r for r in all_results if r.get("status") == "error"]
    passed = [r for r in all_results if r.get("status") == "pass"]

    if args.format == "json":
        print(json.dumps({
            "repo": git_root,
            "results": all_results,
            "pass": len(passed),
            "fail": len(failures),
            "error": len(errors),
        }, indent=2))
    else:
        print(f"🔍 Git Warden — checking {git_root}")
        for r in all_results:
            if r["status"] == "pass":
                icon = "✅"
            elif r["status"] == "error":
                icon = "⚠️"
            else:
                icon = "❌"
            detail = r.get("message", r.get("detail", ""))
            print(f"  {icon} {r['check']}: {detail}")
        if failures:
            print(f"\n❌ {len(failures)} check(s) failed")
            if errors:
                print(f"⚠️  {len(errors)} check(s) had errors")
        elif errors:
            print(f"\n⚠️  {len(errors)} check(s) had errors, none failed")
        else:
            print("\n✅ All checks passed")

    return len(failures)


def cmd_check_msg(args: argparse.Namespace) -> int:
    """Check a commit message file (called by commit-msg hook)."""
    msg_file = args.msg_file
    git_root = _find_git_root()
    if not git_root:
        print("Error: not inside a git repository.", file=sys.stderr)
        return 1

    try:
        with open(msg_file) as f:
            msg = f.read()
    except OSError as e:
        print(f"Error reading commit message: {e}", file=sys.stderr)
        return 1

    config_path = os.path.join(git_root, ".gitwarden.yaml")
    config = _parse_config(config_path)
    results = _check_commit_msg(config, msg)
    failures = [r for r in results if r.get("status") == "fail"]

    if args.format == "json":
        print(json.dumps({"results": results, "fail": len(failures)}, indent=2))
    else:
        for r in results:
            if r["status"] == "fail":
                print(f"❌ {r['detail']}")
            else:
                print(f"✅ Commit message OK: {r.get('message', '')}")

    return len(failures)


def cmd_config(args: argparse.Namespace) -> int:
    git_root = _find_git_root()
    config_path = os.path.join(git_root, ".gitwarden.yaml") if git_root else None

    if args.generate or not config_path or not os.path.exists(config_path):
        if args.format == "json":
            print(json.dumps({"action": "generated", "content": DEFAULT_CONFIG}, indent=2))
        else:
            print(DEFAULT_CONFIG)
        return 0

    # Show existing config
    try:
        with open(config_path) as f:
            content = f.read()
    except OSError:
        content = DEFAULT_CONFIG

    if args.format == "json":
        config = _parse_config(config_path)
        print(json.dumps({"path": config_path, "config": config}, indent=2))
    else:
        print(f"# Config from {config_path}")
        print(content)

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    search_dir = os.path.abspath(args.directory) if hasattr(args, 'directory') else os.getcwd()
    results: list[dict] = []

    for entry in sorted(os.listdir(search_dir)):
        full_path = os.path.join(search_dir, entry)
        if not os.path.isdir(full_path):
            continue
        hooks_dir = os.path.join(full_path, ".git", "hooks")
        if not os.path.isdir(hooks_dir):
            continue

        warden_hooks = []
        for hook_name in ["pre-commit", "commit-msg", "pre-push"]:
            hook_path = os.path.join(hooks_dir, hook_name)
            if os.path.isfile(hook_path):
                try:
                    with open(hook_path) as f:
                        content = f.read()
                    if "Git Warden" in content:
                        warden_hooks.append(hook_name)
                except OSError:
                    pass

        if warden_hooks:
            results.append({
                "repo": entry,
                "path": full_path,
                "hooks": warden_hooks,
            })

    if args.format == "json":
        print(json.dumps({"repositories": results, "count": len(results)}, indent=2))
    else:
        if not results:
            print("No repositories with Git Warden hooks found.")
        else:
            print("🔐 Git Warden — installed hooks")
            print()
            for r in results:
                print(f"  {r['repo']} — {', '.join(r['hooks'])}")
            print(f"\n{len(results)} repositor{'y' if len(results) == 1 else 'ies'} found")

    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────


def add_format_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="Output format (default: text)",
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    p_install = sub.add_parser("install", help="Install hook scripts into a repo")
    p_install.add_argument("--hooks-dir", default=".git/hooks",
                           help="Path to hooks directory (default: .git/hooks)")
    p_install.add_argument("--hooks", default="all",
                           help="Hooks to install: all, pre-commit, commit-msg, pre-push")
    add_format_arg(p_install)

    p_check = sub.add_parser("check", help="Run all installed checks manually")
    p_check.add_argument("--no-bypass", action="store_true",
                         help="Ignore bypass markers")
    add_format_arg(p_check)

    p_check_msg = sub.add_parser("check-msg", help="Check a commit message file (hook internal)")
    p_check_msg.add_argument("msg_file", help="Path to commit message file")
    add_format_arg(p_check_msg)

    p_config = sub.add_parser("config", help="Show or generate a .gitwarden.yaml config")
    p_config.add_argument("--generate", action="store_true",
                          help="Generate a fresh default config")
    add_format_arg(p_config)

    p_status = sub.add_parser("status", help="Show which repos have Warden hooks installed")
    p_status.add_argument("directory", nargs="?", default=".",
                          help="Directory to scan (default: current)")
    add_format_arg(p_status)

    args = p.parse_args(argv)

    if args.command == "install":
        return cmd_install(args)
    elif args.command == "check":
        return cmd_check(args)
    elif args.command == "check-msg":
        return cmd_check_msg(args)
    elif args.command == "config":
        return cmd_config(args)
    elif args.command == "status":
        return cmd_status(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
