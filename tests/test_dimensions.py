"""Pure tests for flexible report-grouping dimension parsing (no DB needed)."""

import pytest

from apitracker.db import DIMENSIONS, parse_dimensions


def test_single_and_multi():
    assert parse_dimensions("app") == ["app"]
    assert parse_dimensions("model") == ["model"]
    assert parse_dimensions("app-provider") == ["app", "provider"]


def test_canonical_order_is_enforced():
    # input order doesn't matter; output is always app, user, provider, model
    assert parse_dimensions("model-app") == ["app", "model"]
    assert parse_dimensions("provider,user,app") == ["app", "user", "provider"]


def test_comma_or_dash_separators():
    assert parse_dimensions("user,model") == parse_dimensions("user-model") == ["user", "model"]


def test_dedup():
    assert parse_dimensions("app-app-provider") == ["app", "provider"]


def test_all_dimensions():
    assert parse_dimensions("app-user-provider-model") == list(DIMENSIONS)


def test_unknown_dimension_raises():
    with pytest.raises(ValueError):
        parse_dimensions("app-bogus")


def test_empty_raises():
    with pytest.raises(ValueError):
        parse_dimensions("")
    with pytest.raises(ValueError):
        parse_dimensions("-")
