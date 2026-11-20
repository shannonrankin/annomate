#!/usr/bin/env -S uv run --script

# /// script
# dependencies = ["nox>=2025.2.9"]
# ///

"""Nox task runner sessions aligned with the Scientific Python Development Guide."""

from __future__ import annotations

import nox

nox.needs_version = ">=2025.2.9"
nox.options.default_venv_backend = "uv|virtualenv"


@nox.session(default=True)
def lint(session: nox.Session) -> None:
    """Run Ruff linter, MyPy static type checks, and Scientific Python sp-repo-review."""
    session.install("--group", "lint", "-e", ".")
    session.run("ruff", "check", ".")
    session.run("mypy")
    session.run("python", "-m", "repo_review", ".")


@nox.session(default=True)
def tests(session: nox.Session) -> None:
    """Run the test suite in offline Demo Mode."""
    session.install("--group", "test", "-e", ".")
    session.run("pytest", *session.posargs, env={"ANNOMATE_DEMO_MODE": "true"})


@nox.session(default=False)
def demo(session: nox.Session) -> None:
    """Launch the Annomate web platform locally in Offline Demo Mode."""
    session.install("-e", ".")
    session.run(
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        env={"ANNOMATE_DEMO_MODE": "true"},
    )


if __name__ == "__main__":
    nox.main()
