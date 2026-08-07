# Git Warden 🔐

**Git hook manager and branch policy enforcer.** Install pre-commit checks, validate branch names, enforce commit message formats. Zero dependencies, pure Python stdlib.

> Part of the DevOps suite — bring CI-style gatekeeping to your local git workflow.

## One tool, many domains

| Domain | What Git Warden does for you |
|---|---|
| 🔒 **Security** | Scans staged diffs for secrets (API keys, private keys, passwords) before they hit the repo |
| 📋 **DevOps** | Enforces branch naming conventions and conventional commit message formats at the hook level |
| 👥 **Team Standards** | Share a `.gitwarden.yaml` config to align every contributor on the same policies |
| 🤖 **Agentic AI** | Structured `--format json` output for CI/CD pipelines and AI agent commit verification |

## Install

```bash
git clone git@github.com:realMNohgee/Git_Warden.git
cd Git_Warden
python3 git_warden.py --help
```

## Quick start

```bash
# Inside any git repo, install hooks
python3 git_warden.py install

# Run checks manually
python3 git_warden.py check

# Generate a config file with defaults
python3 git_warden.py config --generate > .gitwarden.yaml

# See which repos have Warden hooks
python3 git_warden.py status ~/projects

# Check a commit message (used internally by commit-msg hook)
python3 git_warden.py check-msg .git/COMMIT_EDITMSG

# JSON output for CI
python3 git_warden.py check --format json
```

## What It Checks

| Check | What It Does |
|---|---|
| **Branch name** | Validates branch name matches pattern (default: `feature/`, `fix/`, `chore/`, etc.) |
| **Commit message** | Enforces conventional commits format (e.g., `feat: add login`) |
| **File size** | Blocks files larger than 5MB from being committed |
| **Secrets** | Scans for API keys, private keys, and password patterns |

## Configuration

`.gitwarden.yaml` (auto-generated or customized):

```yaml
branch:
  pattern: "^(feature|fix|chore|docs|test|refactor)/[a-z0-9._-]+$"

commit:
  pattern: "^(feat|fix|chore|docs|test|refactor|style|perf|ci|build|revert): "

files:
  max_size_mb: 5
  block_patterns:
    - "-----BEGIN RSA PRIVATE KEY-----"
    - "api_key\\s*=\\s*['\\\"][A-Za-z0-9_-]{20,}['\\\"]"
```

## Subcommands

| Command | Description |
|---|---|
| `install` | Install hook scripts (pre-commit, commit-msg, pre-push) into a git repo |
| `check` | Run all checks manually — branch, secrets, file size |
| `check-msg` | Validate a single commit message file |
| `config` | Show or generate `.gitwarden.yaml` |
| `status` | Scan a directory for repos with Warden hooks installed |

## License

MIT — see [LICENSE](LICENSE).

---

🧰 **[Tool on Hermtica Marketplace](https://hermtica.com/marketplace)** — the open, agent-agnostic marketplace for AI agent tools.
