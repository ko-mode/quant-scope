"""``quantscope`` CLI - data operations.

Phase 1B provides ``seed-securities``. Price / factor / fundamentals ingestion
commands are added in later phases.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

import typer

from quantscope.config import get_settings
from quantscope.data.providers.sec_edgar import SecEdgarSecurityProvider
from quantscope.data.security_seed import run_security_seed
from quantscope.db.session import SessionLocal
from quantscope.logging_setup import configure_json_logging

app = typer.Typer(help="QuantScope data operations.", no_args_is_help=True)


@app.callback()
def _root() -> None:
    """QuantScope data operations (ingestion, seeding)."""
    # Present so Typer keeps sub-command dispatch even with a single command.


@app.command("seed-securities")
def seed_securities(
    source_file: Annotated[
        Path | None,
        typer.Option(
            exists=True,
            dir_okay=False,
            readable=True,
            help="Read a locally downloaded company_tickers_exchange.json instead of fetching from SEC.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(help="Fetch and normalise only; write nothing and record no run."),
    ] = False,
    verbose: Annotated[bool, typer.Option(help="Log at DEBUG.")] = False,
) -> None:
    """Populate the ``security`` table from SEC company/ticker reference data."""
    configure_json_logging(logging.DEBUG if verbose else logging.INFO)
    settings = get_settings()

    provider = SecEdgarSecurityProvider(
        user_agent=settings.sec_user_agent,
        url=settings.sec_company_tickers_url,
        source_file=source_file,
    )

    if dry_run:
        with SessionLocal() as session:
            report = run_security_seed(session, provider, dry_run=True)
    else:
        with SessionLocal() as session:
            report = run_security_seed(session, provider)

    typer.echo(json.dumps(report.as_dict(), default=str))
    raise typer.Exit(0 if report.status != "failed" else 1)


if __name__ == "__main__":  # pragma: no cover
    app()
