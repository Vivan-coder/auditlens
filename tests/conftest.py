"""Shared fixtures: the generated dataset is built once per test session."""

from __future__ import annotations

import pytest

from auditlens.config import Config, load_config
from auditlens.generate import generate


@pytest.fixture(scope="session")
def cfg() -> Config:
    """Default configuration (seed 42, ~50k lines)."""
    return load_config()


@pytest.fixture(scope="session")
def tables(cfg: Config) -> dict:
    """All generated tables for the default configuration."""
    return generate(cfg)


@pytest.fixture(scope="session")
def journal(tables):
    """Journal lines (no labels)."""
    return tables["journal_entries"]


@pytest.fixture(scope="session")
def labels(tables):
    """Ground-truth labels (separate table)."""
    return tables["labels"]


def small_cfg(seed: int) -> Config:
    """A small, fast configuration for reproducibility tests."""
    c = load_config()
    c.generation.seed = seed
    c.generation.target_lines = 6000
    return c
