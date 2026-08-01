"""Core helpers for the PJSK salary calculator."""

from .parser import (
    ParsedWorkbook,
    ScheduleParseError,
    parse_schedule_sheets,
    parse_schedule_workbook,
    read_schedule_workbook,
)
from .salary import SalaryResult, SalaryValidationError, build_default_rates, calculate_salary
from .schedule import (
    build_daily_grids,
    build_horizontal_grid,
    daily_grids_to_blocks,
    daily_grids_to_records,
    horizontal_grid_to_daily_grids,
)

__all__ = [
    "ParsedWorkbook",
    "SalaryResult",
    "SalaryValidationError",
    "ScheduleParseError",
    "build_default_rates",
    "build_daily_grids",
    "build_horizontal_grid",
    "calculate_salary",
    "daily_grids_to_blocks",
    "daily_grids_to_records",
    "horizontal_grid_to_daily_grids",
    "parse_schedule_sheets",
    "parse_schedule_workbook",
    "read_schedule_workbook",
]
