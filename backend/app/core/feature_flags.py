import os
from enum import StrEnum


class FinancialMigrationMode(StrEnum):
    OFF = "OFF"
    SHADOW_ONLY = "SHADOW_ONLY"
    A_B_TEST = "A_B_TEST"
    LLM_PRIMARY = "LLM_PRIMARY"


def get_financial_migration_mode() -> FinancialMigrationMode:
    raw_mode = os.environ.get("YARA_FINANCIAL_MIGRATION_MODE", FinancialMigrationMode.OFF.value)
    try:
        return FinancialMigrationMode(raw_mode)
    except ValueError:
        return FinancialMigrationMode.OFF
