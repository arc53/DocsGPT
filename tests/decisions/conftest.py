"""Shared fixtures for the decision-model tests: the release files recorded from the Hub at the pinned revisions."""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "decisions"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def release():
    return load_fixture("release.json")


@pytest.fixture
def serving_v02():
    return load_fixture("arcd_serving-0.4b-v0.2.json")


@pytest.fixture
def serving_v01():
    return load_fixture("arcd_serving-0.6b-v0.1.json")


@pytest.fixture
def questions_json():
    return load_fixture("questions.json")
