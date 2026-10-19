"""oegem: tools for the Oxford Economics Global Economic Model (GEM) web API.

Pick a model release, read its catalogue and data, define and solve scenarios,
and report the results. All API-touching functions take an `OEClient` first:

    from oegem import OEClient
    client = OEClient()          # token from the OE_TOKEN environment variable
    client = OEClient.demo()     # synthetic offline backend; numbers are NOT model output

The package contains code only: no credentials and no model content.
"""
from __future__ import annotations

__version__ = "0.2.0"

from .client import OEClient, OEError
from .runner import load_run, run
from .scenario import Scenario, load_scenarios

__all__ = ["__version__", "OEClient", "OEError", "Scenario", "load_scenarios", "run", "load_run"]
