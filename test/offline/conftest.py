"""Offline-suite isolation: no real env file, no outbound network.

Provider endpoints, models and keys resolve from the environment and
then the env file. Offline tests must never see a real .env (it may
carry live endpoints and keys), so every test starts with the env
file pointed at a path that does not exist. Tests that need an env
file set STOCKINSIDER_ENV_FILE themselves, which overrides this.

Offline tests never reach the network either (TP-035): every DNS
lookup of a non-local name and every socket connection to a
non-loopback address fails with OSError, so a code path that forgets
its injected transport fails loudly instead of fetching a live feed.
Proxy discovery is disabled as well: a local proxy listens on loopback
and would otherwise carry the traffic out (urllib reads the system
proxy settings, including the Windows registry).
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.request

import pytest

_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex
_REAL_GETADDRINFO = socket.getaddrinfo
_LOCAL_NAMES = {"localhost", "", None}


def _is_loopback(address: object) -> bool:
    if isinstance(address, tuple) and address:
        host = address[0]
        if host in ("localhost", ""):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False
    return True  # AF_UNIX paths and other local families


class OfflineNetworkBlocked(OSError):
    """Raised for any outbound connection attempted by an offline test."""


def _guarded_connect(self, address):  # type: ignore[no-untyped-def]
    if not _is_loopback(address):
        raise OfflineNetworkBlocked(f"offline suite: outbound connection to {address!r} blocked")
    return _REAL_CONNECT(self, address)


def _guarded_connect_ex(self, address):  # type: ignore[no-untyped-def]
    if not _is_loopback(address):
        raise OfflineNetworkBlocked(f"offline suite: outbound connection to {address!r} blocked")
    return _REAL_CONNECT_EX(self, address)


def _guarded_getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
    # DNS is outbound traffic too, and a lookup can stall a test for seconds
    if host not in _LOCAL_NAMES:
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            raise OfflineNetworkBlocked(f"offline suite: DNS lookup of {host!r} blocked") from None
        if not literal.is_loopback:
            raise OfflineNetworkBlocked(f"offline suite: outbound address {host!r} blocked")
    return _REAL_GETADDRINFO(host, *args, **kwargs)


@pytest.fixture(autouse=True)
def _isolated_env_file(tmp_path_factory, monkeypatch):
    missing = tmp_path_factory.mktemp("no-env") / ".env"
    monkeypatch.setenv("STOCKINSIDER_ENV_FILE", str(missing))


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", _guarded_getaddrinfo)
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
