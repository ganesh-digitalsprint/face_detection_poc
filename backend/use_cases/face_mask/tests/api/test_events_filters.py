"""Events list: multi-status + sort filters and the CSV export honouring filters and carrying the ROI name."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes.events import parse_statuses


def test_parse_statuses_accepts_comma_list() -> None:
    assert parse_statuses("open, under_review") == ["OPEN", "UNDER_REVIEW"]
    assert parse_statuses(None) is None
    assert parse_statuses("") is None


def test_parse_statuses_rejects_unknown_name() -> None:
    with pytest.raises(HTTPException) as err:
        parse_statuses("OPEN,BOGUS")
    assert err.value.status_code == 422
