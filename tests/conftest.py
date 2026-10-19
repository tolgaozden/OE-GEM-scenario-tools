"""Shared fixtures. Every test runs offline against the synthetic demo backend."""
import pytest

from oegem import OEClient


@pytest.fixture
def client():
    """A fresh demo client (synthetic FakeSession backend, dummy token)."""
    return OEClient.demo()


@pytest.fixture
def release(client):
    """Resource dict of the newest 5-year demo release."""
    from oegem.resources import resolve_release

    return resolve_release(client, "latest:5yr")
