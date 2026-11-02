"""Typed loading of config.yaml (validated with pydantic so typos fail early)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "config.yaml"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompanyCfg(_Strict):
    name: str
    currency: str
    fiscal_year: int


class CalendarCfg(_Strict):
    country: str
    period_close_days: int = Field(ge=0)


class RoleCfg(_Strict):
    rank: int
    approval_limit: float = Field(ge=0)
    count: int = Field(ge=0)


class GenerationCfg(_Strict):
    seed: int
    target_lines: int = Field(gt=1000)
    n_vendors: int = Field(gt=10)
    n_employees: int = Field(gt=5)
    sales_seasonality: list[float] = Field(min_length=12, max_length=12)
    purchase_seasonality: list[float] = Field(min_length=12, max_length=12)


class AnomalyCountsCfg(_Strict):
    duplicate_payment: int = Field(ge=0)
    split_purchase_groups: int = Field(ge=0)
    weekend_holiday_posting: int = Field(ge=0)
    round_amount: int = Field(ge=0)
    same_creator_approver: int = Field(ge=0)
    post_close_posting: int = Field(ge=0)
    backdated_posting: int = Field(ge=0)
    ghost_vendor_bank: int = Field(ge=0)
    ghost_vendor_address: int = Field(ge=0)
    bank_change_large_payment: int = Field(ge=0)
    invoice_sequence_gap: int = Field(ge=0)
    invoice_sequence_out_of_order: int = Field(ge=0)
    unusual_pairing: int = Field(ge=0)
    rare_user_account: int = Field(ge=0)
    benford_vendor_invoices: int = Field(ge=0)
    large_manual_period_end: int = Field(ge=0)


class AccountsCfg(_Strict):
    payables: int
    cash: int


class DuplicatesCfg(_Strict):
    window_days: int = Field(gt=0)
    amount_tolerance_pct: float = Field(ge=0)
    min_amount: float = Field(ge=0)


class SplitCfg(_Strict):
    band_low_pct: float = Field(gt=0, lt=100)
    window_days: int = Field(gt=0)
    min_count: int = Field(ge=2)


class TimingCfg(_Strict):
    weekend_sources: list[str]
    backdate_days: int = Field(gt=0)


class RoundCfg(_Strict):
    multiple: int = Field(gt=0)
    min_amount: float = Field(ge=0)
    sources: list[str]
    recurring_repeat_exempt: int = Field(ge=2)


class MaterialityCfg(_Strict):
    amount: float = Field(gt=0)
    period_end_business_days: int = Field(gt=0)
    sources: list[str]


class BankChangeCfg(_Strict):
    window_days: int = Field(gt=0)
    min_amount: float = Field(ge=0)
    median_multiple: float = Field(gt=0)


class SequenceCfg(_Strict):
    max_gap: int = Field(gt=0)


class BenfordCfg(_Strict):
    min_invoices: int = Field(ge=10)
    p_threshold: float = Field(gt=0, lt=1)


class PairingsCfg(_Strict):
    rare_pair_max_count: int = Field(ge=0)
    rare_user_account_max_count: int = Field(ge=0)
    user_min_entries: int = Field(ge=1)


class RulesCfg(_Strict):
    duplicates: DuplicatesCfg
    split_purchase: SplitCfg
    timing: TimingCfg
    round_amount: RoundCfg
    materiality: MaterialityCfg
    bank_change: BankChangeCfg
    invoice_sequence: SequenceCfg
    benford: BenfordCfg
    pairings: PairingsCfg


class Config(_Strict):
    """Whole configuration file."""

    company: CompanyCfg
    calendar: CalendarCfg
    roles: dict[str, RoleCfg]
    generation: GenerationCfg
    anomalies: AnomalyCountsCfg
    accounts: AccountsCfg
    rules: RulesCfg


def load_config(path: Path | str | None = None) -> Config:
    """Load and validate the YAML config (defaults to the repo's config.yaml)."""
    with open(path or DEFAULT_CONFIG_PATH, encoding="utf-8") as fh:
        return Config.model_validate(yaml.safe_load(fh))


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Cached default config."""
    return load_config()
