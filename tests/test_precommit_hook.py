import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOK_SCRIPT = REPO_ROOT / "scripts" / "pre-commit-privacy-guard.sh"


def _run_git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def test_hook_blocks_staging_private_path(tmp_path):
    """Real shell-level test: initializes a throwaway git repo, installs
    the actual hook script, attempts `git add` + `git commit` on a file
    under data/private/, and confirms the hook rejects it -- not a unit
    test of the shell script's logic in isolation."""
    repo = tmp_path / "throwaway"
    repo.mkdir()
    _run_git(["init", "-q"], cwd=repo)
    _run_git(["config", "user.email", "test@example.com"], cwd=repo)
    _run_git(["config", "user.name", "test"], cwd=repo)

    hooks_dir = repo / ".git" / "hooks"
    hook_dest = hooks_dir / "pre-commit"
    hook_dest.write_text(HOOK_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    hook_dest.chmod(0o755)

    private_dir = repo / "data" / "private"
    private_dir.mkdir(parents=True)
    (private_dir / "leak.txt").write_text("real content", encoding="utf-8")

    _run_git(["add", "-f", "data/private/leak.txt"], cwd=repo)
    result = _run_git(["commit", "-m", "should be blocked"], cwd=repo)

    assert result.returncode != 0
    assert "BLOCKED" in result.stderr or "BLOCKED" in result.stdout


def test_hook_allows_ordinary_file(tmp_path):
    repo = tmp_path / "throwaway2"
    repo.mkdir()
    _run_git(["init", "-q"], cwd=repo)
    _run_git(["config", "user.email", "test@example.com"], cwd=repo)
    _run_git(["config", "user.name", "test"], cwd=repo)

    hooks_dir = repo / ".git" / "hooks"
    hook_dest = hooks_dir / "pre-commit"
    hook_dest.write_text(HOOK_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    hook_dest.chmod(0o755)

    (repo / "ordinary.py").write_text("x = 1\n", encoding="utf-8")
    _run_git(["add", "ordinary.py"], cwd=repo)
    result = _run_git(["commit", "-m", "fine"], cwd=repo)

    assert result.returncode == 0
