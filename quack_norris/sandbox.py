"""``quack-norris-sandbox`` — run an agent in an isolated worktree container.

Creates a git worktree for a branch, then launches the agent inside a
container with that worktree mounted at ``/workspace`` as the working
directory, so quack-norris (or any other AI agent) can work there without
touching the main checkout.

Pass ``--shell <cmd>`` to run an arbitrary command instead of the agent
(e.g. ``--shell bash`` for a debug shell).

With ``--no-container`` the container is skipped and the agent (or
``--shell`` command) is launched directly in the worktree on the host.

Image resolution, in order: ``--image``, then an explicitly passed ``--agent``
(the bundled ``sandbox.Dockerfile`` stage for quack-norris, Devin CLI, or
Claude Code — built once, then cached), then a ``Dockerfile`` in the worktree
(built), then ``sandbox.image`` from config, then the bundled stage for the
default agent. Explicit flags win over the worktree's Dockerfile, with a
warning when one is skipped.

The selected agent's host config (see ``_AGENT_CONFIG_DIRS``) is mounted so it
is already authenticated inside the container (``--no-config`` opts out).

Global config (``~/.config/quack-norris/config.yaml``)::

    sandbox:
      runtime: podman        # default: docker, else podman
      agent: claude          # default: quack

Setting ``image:`` there (or ``--image``) bypasses the bundled image, so that
image must come with the agent already installed — plain ``python:3.12`` will
leave you in a container with no agent and no uv.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_DEFAULT_DOCKERFILE = Path(__file__).with_name("sandbox.Dockerfile")

# agent → host config paths to bind-mount, each as (host, container). The
# container runs as root, so config lands where the agent looks for it under
# /root. Paths that don't exist on the host are skipped.
_QUACK_HOME = Path(os.environ.get("QUACK_NORRIS_HOME", Path.home() / ".config/quack-norris"))
_HOME = Path.home()
# The Devin CLI splits its state: settings in ~/.config/devin (XDG_CONFIG_HOME)
# but the login in ~/.local/share/devin/credentials.toml (XDG_DATA_HOME) — the
# path `devin auth status` reports. On Windows both collapse into %APPDATA%\devin,
# which also doubles as the Devin IDE's Electron user-data dir; mounting that
# whole directory would hand the container its caches and live session
# databases, so only the individual files are mounted.
_DEVIN_WIN = Path(os.environ["APPDATA"]) / "devin" if os.environ.get("APPDATA") else None
_DEVIN_CONFIG = (
    _DEVIN_WIN if os.name == "nt" and _DEVIN_WIN
    else Path(os.environ.get("XDG_CONFIG_HOME", _HOME / ".config")) / "devin"
)
_DEVIN_DATA = (
    _DEVIN_WIN if os.name == "nt" and _DEVIN_WIN
    else Path(os.environ.get("XDG_DATA_HOME", _HOME / ".local" / "share")) / "devin"
)
_AGENT_CONFIG_DIRS = {
    "quack": [(_QUACK_HOME, "/root/.config/quack-norris")],
    "copilot": [(_HOME / ".copilot", "/root/.copilot")],
    "devin": [
        (_DEVIN_DATA / "credentials.toml", "/root/.local/share/devin/credentials.toml"),
        (_DEVIN_CONFIG / "config.json", "/root/.config/devin/config.json"),
        (_DEVIN_CONFIG / "mcp_config.json", "/root/.config/devin/mcp_config.json"),
    ],
    # ~/.claude holds sessions and settings, but onboarding/auth/trust state
    # lives in the separate ~/.claude.json — without it every sandbox start
    # asks to confirm usage again.
    "claude": [
        (_HOME / ".claude", "/root/.claude"),
        (_HOME / ".claude.json", "/root/.claude.json"),
    ],
}

# Default command to launch each agent inside the container / worktree.
_AGENT_CMD = {
    "quack": "quack-norris --resume",
    "copilot": "copilot",
    "devin": "devin",
    "claude": "claude",
}


def _build(runtime: str, tag: str, dockerfile: Path, context: Path, target: str = "") -> str:
    """Build *dockerfile* as *tag* and return the tag. Exits on failure."""
    cmd = [runtime, "build", "-t", tag, "-f", str(dockerfile)]
    if target:
        cmd += ["--target", target]
    cmd.append(str(context))
    if subprocess.run(cmd).returncode != 0:
        sys.exit(f"Container build failed: {' '.join(cmd)}")
    return tag


def _sandbox_config() -> dict:
    from quack_norris.core.llm.llm import _load_global_raw
    cfg = _load_global_raw().get("sandbox") or {}
    return cfg if isinstance(cfg, dict) else {}


def _pick_runtime(configured: str | None) -> str:
    for candidate in [configured] if configured else ["docker", "podman"]:
        if candidate and shutil.which(candidate):
            return candidate
    sys.exit(f"Container runtime not found on PATH: {configured or 'docker/podman'}")


def _repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    if out.returncode != 0:
        sys.exit("Not inside a git repository.")
    return Path(out.stdout.strip())


def _list_worktrees(repo: Path) -> list[tuple[str, Path]]:
    """Return [(branch_name, worktree_path), ...] for every non-main worktree."""
    out = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], capture_output=True, text=True, cwd=repo
    )
    if out.returncode != 0:
        sys.exit("Could not list worktrees.")
    entries: list[tuple[str, Path]] = []
    wt_path: Path | None = None
    branch: str | None = None
    for line in out.stdout.splitlines():
        if line.startswith("worktree "):
            wt_path = Path(line.split(" ", 1)[1])
            branch = None
        elif line.startswith("branch "):
            branch = line.split("refs/heads/", 1)[-1]
        elif line == "":
            if wt_path and branch and wt_path.resolve() != repo.resolve():
                entries.append((branch, wt_path))
            wt_path = None
            branch = None
    # flush last stanza (no trailing blank line in some git versions)
    if wt_path and branch and wt_path.resolve() != repo.resolve():
        entries.append((branch, wt_path))
    return entries


def _pick_worktree(repo: Path) -> tuple[str, Path]:
    """Interactively pick a worktree; returns (branch, path)."""
    worktrees = _list_worktrees(repo)
    if not worktrees:
        sys.exit("No existing worktrees found (other than the main checkout).")
    print("Select a worktree to resume:", file=sys.stderr)
    for i, (branch, wt_path) in enumerate(worktrees, 1):
        print(f"  {i}) {branch}  ({wt_path})", file=sys.stderr)
    print(file=sys.stderr)
    try:
        raw = input(f"Enter number [1-{len(worktrees)}]: ").strip()
        idx = int(raw) - 1
        if not (0 <= idx < len(worktrees)):
            raise ValueError
    except (ValueError, EOFError):
        sys.exit("Invalid selection.")
    return worktrees[idx]


def main() -> None:
    p = argparse.ArgumentParser(prog="quack-norris-sandbox", description=__doc__)
    p.add_argument("branch", nargs="?", help="Branch to work on (created from HEAD if missing); "
                   "omit when using --resume")
    p.add_argument("path", nargs="?", help="Worktree location (default: ../<repo>-<branch>)")
    p.add_argument("--resume", action="store_true",
                   help="Interactively pick an existing worktree to resume instead of "
                        "creating a new one")
    p.add_argument("--image", help="Container image (overrides the worktree's Dockerfile)")
    p.add_argument("--agent", choices=sorted(_AGENT_CONFIG_DIRS),
                   help="Agent whose bundled image to use, overriding the worktree's "
                        "Dockerfile (default: sandbox.agent, else quack)")
    p.add_argument("--no-container", action="store_true",
                   help="Only create the worktree and print the cd for it (or run --shell there)")
    p.add_argument("--no-config", action="store_true",
                   help="Do not mount the agent's config directory into the container")
    p.add_argument("--shell",
                   help="Command to run in the container (default: bash), or in the worktree "
                        "on the host with --no-container")
    rt = p.add_mutually_exclusive_group()
    rt.add_argument("--runtime", help="Container runtime, overrides sandbox.runtime from config")
    rt.add_argument("--docker", dest="runtime", action="store_const", const="docker",
                    help="Shorthand for --runtime docker")
    rt.add_argument("--podman", dest="runtime", action="store_const", const="podman",
                    help="Shorthand for --runtime podman")
    args = p.parse_args()

    repo = _repo_root()

    if args.resume:
        branch, target = _pick_worktree(repo)
        if args.path:
            target = Path(args.path).resolve()
        if args.branch:
            branch = args.branch
        safe = branch.replace("/", "-")
    else:
        if not args.branch:
            p.error("the following arguments are required: branch (or use --resume)")
        branch = args.branch
        safe = branch.replace("/", "-")
        target = Path(args.path).resolve() if args.path else repo.parent / f"{repo.name}-{safe}"

    if not target.exists():
        add = subprocess.run(["git", "worktree", "add", "-B", branch, str(target)], cwd=repo)
        if add.returncode != 0:
            sys.exit(add.returncode)

    if args.no_container:
        if args.shell:
            print(f"Worktree: {target}\nRunning:  {args.shell}  (no container)", file=sys.stderr)
            sys.exit(subprocess.run(args.shell, cwd=target, shell=True).returncode)
        # Default: launch the agent in the worktree directory on the host.
        _cfg = _sandbox_config()
        _agent = args.agent or _cfg.get("agent") or "quack"
        if _agent not in _AGENT_CMD:
            sys.exit(f"Unknown agent '{_agent}'. Choose one of: {', '.join(sorted(_AGENT_CMD))}")
        cmd_str = _AGENT_CMD[_agent]
        print(f"Worktree: {target}\nLaunching: {cmd_str}  (no container)", file=sys.stderr)
        sys.exit(subprocess.run(cmd_str, cwd=target, shell=True).returncode)

    cfg = _sandbox_config()
    runtime = _pick_runtime(args.runtime or cfg.get("runtime"))
    agent = args.agent or cfg.get("agent") or "quack"
    if agent not in _AGENT_CONFIG_DIRS:
        sys.exit(f"Unknown agent '{agent}'. Choose one of: {', '.join(sorted(_AGENT_CONFIG_DIRS))}")

    # Explicit flags win over the worktree's Dockerfile, which in turn wins
    # over config, being the more specific choice.
    dockerfile = target / "Dockerfile"
    if args.image:
        source = "--image"
        image = args.image
    elif dockerfile.exists() and not args.agent:
        source = "the worktree's own Dockerfile"
        image = _build(runtime, f"sandbox-{safe.lower()}:latest", dockerfile, target)
    elif not args.agent and cfg.get("image"):
        source = "sandbox.image in config — no agent installed for you"
        image = cfg["image"]
    else:
        source = f"bundled default, {agent} stage"
        if dockerfile.exists():
            print(f"Warning: ignoring the worktree's Dockerfile because --agent {agent} was "
                  f"given; using the bundled {agent} image instead. Drop --agent to build the "
                  f"Dockerfile, or pass --image for a custom image.", file=sys.stderr)
        # Bundled default. It COPYs nothing, so an empty build context keeps
        # the daemon upload at zero.
        with tempfile.TemporaryDirectory() as empty:
            image = _build(runtime, f"sandbox-{agent}:latest", _DEFAULT_DOCKERFILE,
                           Path(empty), agent)

    cmd = [runtime, "run", "--rm", "-it", "-v", f"{target}:/workspace", "-w", "/workspace"]
    # The agent inside needs its config (and a writable place for sessions).
    # Note: this exposes any credentials in that directory to the container.
    seeded: list[tuple[str, str]] = []  # (path under /seed, path the agent reads)
    if not args.no_config:
        for i, (host_cfg, container_cfg) in enumerate(_AGENT_CONFIG_DIRS[agent]):
            if not host_cfg.exists():
                continue
            if host_cfg.is_dir():
                cmd += ["-v", f"{host_cfg}:{container_cfg}"]
            else:
                # A bind-mounted file cannot be replaced by rename ("device or
                # resource busy"), which is how these agents save their config.
                # So mount it aside and copy it into place / back out again.
                cmd += ["-v", f"{host_cfg}:/seed/{i}"]
                seeded.append((f"/seed/{i}", container_cfg))
            if agent == "quack":
                cmd += ["-e", f"QUACK_NORRIS_HOME={container_cfg}"]

    # Explicit command: don't rely on the image's CMD (python images default to
    # a Python REPL, and a stage's inherited CMD is not always preserved).
    # Default: launch the agent; --shell overrides with an arbitrary command.
    inner = args.shell or _AGENT_CMD[agent]
    if seeded:
        # mkdir -p: a seeded file may live in a directory the image doesn't have
        # (e.g. /root/.config/devin).
        pre = "; ".join(f"mkdir -p $(dirname {p}); cp {s} {p}" for s, p in seeded)
        # Written with `cat >` rather than `cp`/`mv`: an in-place write is the
        # only way to update a bind-mounted file.
        post = "; ".join(f"cat {p} > {s}" for s, p in seeded)
        inner = f"{pre}; {inner}; {post}"
    cmd += [image, "bash", "-c", inner]
    print(f"Worktree: {target}\nImage:    {image}  ({source})\nRunning:  {' '.join(cmd)}")
    sys.exit(subprocess.run(cmd, cwd=target).returncode)


if __name__ == "__main__":
    main()
