from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


RATE_COLUMNS = ["班组", "岗位", "白班价", "夜班价"]


class SalaryValidationError(ValueError):
    """Raised when salary settings are incomplete or invalid."""


@dataclass(frozen=True)
class SalaryResult:
    summary: pd.DataFrame
    detail: pd.DataFrame

    @property
    def total_hours(self) -> float:
        return float(self.summary["总工时"].sum())

    @property
    def total_salary(self) -> float:
        return float(self.summary["总工资"].sum())


def build_default_rates(
    records: pd.DataFrame, day_rate: float = 20, night_rate: float = 30
) -> pd.DataFrame:
    unique_roles = records[["team", "role"]].drop_duplicates(ignore_index=True)
    rates = unique_roles.rename(columns={"team": "班组", "role": "岗位"})
    rates["白班价"] = float(day_rate)
    rates["夜班价"] = float(night_rate)
    return rates[RATE_COLUMNS]


def calculate_salary(
    records: pd.DataFrame,
    rates: pd.DataFrame,
    day_start_hour: int = 8,
    night_start_hour: int = 20,
) -> SalaryResult:
    if records.empty:
        raise SalaryValidationError("没有可计算的排班记录。")
    if not 0 <= day_start_hour <= 23 or not 0 <= night_start_hour <= 23:
        raise SalaryValidationError("白班和夜班开始时间必须在 0–23 点之间。")
    if day_start_hour == night_start_hour:
        raise SalaryValidationError("白班开始时间不能和夜班开始时间相同。")

    missing_columns = [column for column in RATE_COLUMNS if column not in rates.columns]
    if missing_columns:
        raise SalaryValidationError(f"工价设置缺少列：{', '.join(missing_columns)}")

    normalized_rates = rates[RATE_COLUMNS].copy()
    normalized_rates["班组"] = normalized_rates["班组"].astype(str).str.strip()
    normalized_rates["岗位"] = normalized_rates["岗位"].astype(str).str.strip()
    for column in ("白班价", "夜班价"):
        normalized_rates[column] = pd.to_numeric(normalized_rates[column], errors="coerce")
        if normalized_rates[column].isna().any():
            raise SalaryValidationError(f"{column}中存在空值或非数字。")
        if (normalized_rates[column] < 0).any():
            raise SalaryValidationError(f"{column}不能为负数。")

    duplicated = normalized_rates.duplicated(["班组", "岗位"], keep=False)
    if duplicated.any():
        duplicate_names = normalized_rates.loc[duplicated, ["班组", "岗位"]].drop_duplicates()
        labels = [f"{row.班组}/{row.岗位}" for row in duplicate_names.itertuples()]
        raise SalaryValidationError(f"工价设置存在重复岗位：{', '.join(labels)}")

    detail = records.copy()
    detail = detail.merge(
        normalized_rates,
        how="left",
        left_on=["team", "role"],
        right_on=["班组", "岗位"],
        validate="many_to_one",
    )
    missing_rates = detail[detail["白班价"].isna()][["team", "role"]].drop_duplicates()
    if not missing_rates.empty:
        labels = [f"{row.team}/{row.role}" for row in missing_rates.itertuples()]
        raise SalaryValidationError(f"以下岗位没有设置工价：{', '.join(labels)}")

    day_start = day_start_hour * 60
    night_start = night_start_hour * 60
    split_hours = detail.apply(
        lambda row: _split_shift_hours(
            int(row["start_minutes"]),
            int(row["end_minutes"]),
            day_start,
            night_start,
        ),
        axis=1,
        result_type="expand",
    )
    split_hours.columns = ["白班工时", "夜班工时"]
    detail[["白班工时", "夜班工时"]] = split_hours

    is_day_only = detail["夜班工时"] == 0
    is_night_only = detail["白班工时"] == 0
    detail["班次"] = "跨班"
    detail.loc[is_day_only, "班次"] = "白班"
    detail.loc[is_night_only, "班次"] = "夜班"
    detail["白班工资"] = (detail["白班工时"] * detail["白班价"]).round(2)
    detail["夜班工资"] = (detail["夜班工时"] * detail["夜班价"]).round(2)
    detail["工资"] = (detail["白班工资"] + detail["夜班工资"]).round(2)

    grouped = (
        detail.groupby(["team", "person"], sort=False, as_index=True)
        .agg(
            白班工时=("白班工时", "sum"),
            夜班工时=("夜班工时", "sum"),
            总工时=("duration_hours", "sum"),
            白班工资=("白班工资", "sum"),
            夜班工资=("夜班工资", "sum"),
            总工资=("工资", "sum"),
        )
    )
    role_hours = detail.pivot_table(
        index=["team", "person"],
        columns="role",
        values="duration_hours",
        aggfunc="sum",
        fill_value=0,
        sort=False,
    )
    role_hours.columns = [f"{column}工时" for column in role_hours.columns]
    summary = role_hours.join(grouped, how="outer").reset_index()
    summary = summary.rename(columns={"team": "班组", "person": "姓名"})
    summary = summary.sort_values(["班组", "总工资"], ascending=[True, False], kind="stable")
    numeric_columns = summary.columns.difference(["班组", "姓名"])
    summary[numeric_columns] = summary[numeric_columns].astype(float).round(2)

    detail_display = detail[
        [
            "team",
            "date",
            "time_slot",
            "role",
            "person",
            "班次",
            "duration_hours",
            "白班工时",
            "夜班工时",
            "白班价",
            "夜班价",
            "工资",
            "source_cell",
        ]
    ].rename(
        columns={
            "team": "班组",
            "date": "日期",
            "time_slot": "时间段",
            "role": "岗位",
            "person": "姓名",
            "duration_hours": "工时",
            "source_cell": "来源单元格",
        }
    )
    detail_display["日期"] = pd.to_datetime(detail_display["日期"])
    return SalaryResult(summary.reset_index(drop=True), detail_display.reset_index(drop=True))


def _split_shift_hours(
    start_minutes: int,
    end_minutes: int,
    day_start_minutes: int,
    night_start_minutes: int,
) -> tuple[float, float]:
    """Split one schedule interval against repeating daily day/night boundaries."""

    total_minutes = end_minutes - start_minutes
    if total_minutes <= 0:
        total_minutes += 24 * 60

    interval_end = start_minutes + total_minutes
    day_minutes = 0

    for day_offset in range(-1, 3):
        offset = day_offset * 24 * 60
        if day_start_minutes < night_start_minutes:
            day_interval_start = day_start_minutes + offset
            day_interval_end = night_start_minutes + offset
        else:
            day_interval_start = day_start_minutes + offset
            day_interval_end = night_start_minutes + offset + 24 * 60

        overlap = max(
            0,
            min(interval_end, day_interval_end)
            - max(start_minutes, day_interval_start),
        )
        day_minutes += overlap

    night_minutes = total_minutes - day_minutes
    return day_minutes / 60, night_minutes / 60
