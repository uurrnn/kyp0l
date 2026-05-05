"""Retry behavior for OpenStatesScraper._get.

The free-tier API enforces a tighter per-minute burst than the daily counter
suggests, so transient 429s are common. _get must retry through them rather
than failing the whole job. Same for transient ReadTimeouts and 5xxs.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
import requests

from scrapers.openstates import OpenStatesScraper


class FakeResponse:
    def __init__(self, status: int, body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if 400 <= self.status_code:
            raise requests.exceptions.HTTPError(f"{self.status_code} Error", response=self)

    def json(self) -> dict[str, Any]:
        return self._body


class FakeSession:
    """Returns the next queued response or raises the next queued exception."""

    def __init__(self) -> None:
        self.queue: list[FakeResponse | Exception] = []
        self.headers: dict[str, str] = {}
        self.calls = 0

    def get(self, url: str, params: dict[str, Any] | None = None, timeout: int = 30) -> FakeResponse:
        self.calls += 1
        if not self.queue:
            raise AssertionError(f"FakeSession ran out of queued responses on call {self.calls} to {url}")
        next_item = self.queue.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests should not actually sleep."""
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)


def make_scraper() -> tuple[OpenStatesScraper, FakeSession]:
    fake = FakeSession()
    s = OpenStatesScraper.__new__(OpenStatesScraper)
    s.api_key = "fake"
    s.jurisdiction = "ky"
    s.session = fake  # type: ignore[assignment]
    return s, fake


def test_retries_on_429_then_succeeds() -> None:
    s, fake = make_scraper()
    fake.queue = [
        FakeResponse(429, headers={"Retry-After": "1"}),
        FakeResponse(200, body={"ok": True}),
    ]
    out = s._get("/jurisdictions/ky")
    assert out == {"ok": True}
    assert fake.calls == 2


def test_retries_on_500_then_succeeds() -> None:
    s, fake = make_scraper()
    fake.queue = [
        FakeResponse(500),
        FakeResponse(200, body={"ok": True}),
    ]
    out = s._get("/jurisdictions/ky")
    assert out == {"ok": True}
    assert fake.calls == 2


def test_retries_on_read_timeout_then_succeeds() -> None:
    s, fake = make_scraper()
    fake.queue = [
        requests.exceptions.ReadTimeout("simulated"),
        FakeResponse(200, body={"ok": True}),
    ]
    out = s._get("/jurisdictions/ky")
    assert out == {"ok": True}
    assert fake.calls == 2


def test_retries_through_multiple_429s_then_succeeds() -> None:
    s, fake = make_scraper()
    fake.queue = [
        FakeResponse(429, headers={"Retry-After": "1"}),
        FakeResponse(429, headers={"Retry-After": "1"}),
        FakeResponse(429, headers={"Retry-After": "1"}),
        FakeResponse(200, body={"ok": True}),
    ]
    out = s._get("/jurisdictions/ky")
    assert out == {"ok": True}
    assert fake.calls == 4


def test_gives_up_after_max_attempts_on_persistent_429() -> None:
    s, fake = make_scraper()
    fake.queue = [
        FakeResponse(429, headers={"Retry-After": "1"}),
        FakeResponse(429, headers={"Retry-After": "1"}),
        FakeResponse(429, headers={"Retry-After": "1"}),
        FakeResponse(429, headers={"Retry-After": "1"}),
    ]
    with pytest.raises(requests.exceptions.HTTPError):
        s._get("/jurisdictions/ky")
    assert fake.calls == 4


def test_gives_up_after_max_attempts_on_persistent_timeout() -> None:
    s, fake = make_scraper()
    fake.queue = [
        requests.exceptions.ReadTimeout("t1"),
        requests.exceptions.ReadTimeout("t2"),
        requests.exceptions.ReadTimeout("t3"),
        requests.exceptions.ReadTimeout("t4"),
    ]
    with pytest.raises(requests.exceptions.ReadTimeout):
        s._get("/jurisdictions/ky")
    assert fake.calls == 4


def test_4xx_other_than_429_does_not_retry() -> None:
    """A 401 or 404 means we have a bug, not a transient error — fail loud."""
    s, fake = make_scraper()
    fake.queue = [FakeResponse(401)]
    with pytest.raises(requests.exceptions.HTTPError):
        s._get("/jurisdictions/ky")
    assert fake.calls == 1
