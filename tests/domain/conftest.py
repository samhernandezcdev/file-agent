"""Shared fixtures for domain model tests."""

from datetime import UTC, datetime

import pytest

VALID_SHA256 = "a" * 64


@pytest.fixture
def valid_sha256() -> str:
    return VALID_SHA256


@pytest.fixture
def utc_now() -> datetime:
    return datetime.now(UTC)
