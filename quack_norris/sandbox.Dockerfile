# Default sandbox images for `quack-norris-sandbox`, one stage per agent.
# Built with `--target quack|devin|claude` (see --agent), and only used when
# the worktree has no Dockerfile of its own and no image is configured.

FROM python:3.12-slim AS base
# pipefail so a failing installer in a `curl | bash` pipe fails the build
# instead of being masked by the exit code of the shell.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
# curl is needed by the uv, Devin and Claude Code installers; git because the
# mounted worktree is a git checkout.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"
WORKDIR /workspace
CMD ["bash"]

FROM base AS quack
ARG QUACK_NORRIS_REF=main
RUN uv tool install "https://github.com/penguinmenac3/quack-norris/archive/refs/heads/${QUACK_NORRIS_REF}.tar.gz"

FROM base AS devin
# The installer ends with an interactive `devin setup` (login), which cannot
# succeed during a build — so ignore its exit code and verify the binary
# instead. Log in at first use inside the container.
RUN curl -fsSL https://cli.devin.ai/install.sh | bash || true; \
    test -x /root/.local/bin/devin

FROM base AS claude
RUN curl -fsSL https://claude.ai/install.sh | bash
