from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping

import pandas as pd

from .parser import BLOCK_COLUMNS, RECORD_COLUMNS


TIME_COLUMN = "时间"
START_MINUTES_COLUMN = "_start_minutes"


def build_daily_grids(
    records: pd.DataFrame,
    blocks: pd.DataFrame,
) -> tuple[dict[str, dict[dt.date, pd.DataFrame]], int]:
    """Convert parsed schedule records into editable, full-day grids."""

    step_minutes = infer_time_step(records)
    roles_by_team = _roles_by_team(records, blocks)
    dates_by_team = _dates_by_team(records, blocks)

    # A record crossing midnight needs a grid for the following calendar date.
    for row in records.itertuples(index=False):
        start = int(row.start_minutes)
        end = int(row.end_minutes)
        if end <= start:
            end += 24 * 60
        if end > 24 * 60:
            dates_by_team.setdefault(str(row.team), []).append(
                pd.Timestamp(row.date).date() + dt.timedelta(days=1)
            )

    grids: dict[str, dict[dt.date, pd.DataFrame]] = {}
    for team, roles in roles_by_team.items():
        team_dates = sorted(set(dates_by_team.get(team, [])))
        grids[team] = {
            schedule_date: _empty_daily_grid(roles, step_minutes)
            for schedule_date in team_dates
        }

    for row in records.itertuples(index=False):
        team = str(row.team)
        role = str(row.role)
        person = _clean_cell(row.person)
        schedule_date = pd.Timestamp(row.date).date()
        start = int(row.start_minutes)
        end = int(row.end_minutes)
        if end <= start:
            end += 24 * 60

        for minute in range(start, end, step_minutes):
            date_offset, minute_of_day = divmod(minute, 24 * 60)
            target_date = schedule_date + dt.timedelta(days=date_offset)
            if target_date not in grids[team]:
                grids[team][target_date] = _empty_daily_grid(
                    roles_by_team[team], step_minutes
                )
            row_index = minute_of_day // step_minutes
            grids[team][target_date].iat[
                row_index, grids[team][target_date].columns.get_loc(role)
            ] = person

    for team in grids:
        grids[team] = dict(sorted(grids[team].items()))
    return grids, step_minutes


def daily_grids_to_records(
    grids: Mapping[str, Mapping[dt.date, pd.DataFrame]],
    step_minutes: int,
) -> pd.DataFrame:
    """Convert user-edited daily grids back into salary calculation records."""

    rows: list[dict[str, object]] = []
    for team, date_grids in grids.items():
        for schedule_date, frame in sorted(date_grids.items()):
            role_columns = [
                str(column)
                for column in frame.columns
                if column not in {TIME_COLUMN, START_MINUTES_COLUMN}
            ]
            ordered = frame.sort_values(START_MINUTES_COLUMN, kind="stable")
            for _, grid_row in ordered.iterrows():
                start_minutes = int(grid_row[START_MINUTES_COLUMN])
                end_minutes = min(start_minutes + step_minutes, 24 * 60)
                time_slot = format_time_slot(start_minutes, end_minutes)
                for role in role_columns:
                    person = _clean_cell(grid_row[role])
                    if not person:
                        continue
                    rows.append(
                        {
                            "team": str(team),
                            "date": schedule_date,
                            "time_slot": time_slot,
                            "start_minutes": start_minutes,
                            "end_minutes": end_minutes,
                            "duration_hours": step_minutes / 60,
                            "role": role,
                            "person": person,
                            "source_cell": "网页排班",
                        }
                    )

    result = pd.DataFrame.from_records(rows, columns=RECORD_COLUMNS)
    if not result.empty:
        result["date"] = pd.to_datetime(result["date"])
    return result


def daily_grids_to_blocks(
    grids: Mapping[str, Mapping[dt.date, pd.DataFrame]],
) -> pd.DataFrame:
    """Build compact block metadata for the normalized daily grids."""

    rows: list[dict[str, object]] = []
    for team, date_grids in grids.items():
        for schedule_date, frame in sorted(date_grids.items()):
            roles = [
                str(column)
                for column in frame.columns
                if column not in {TIME_COLUMN, START_MINUTES_COLUMN}
            ]
            assignments = sum(
                bool(_clean_cell(value))
                for role in roles
                for value in frame[role].tolist()
            )
            rows.append(
                {
                    "team": str(team),
                    "date": schedule_date,
                    "roles": "、".join(roles),
                    "time_slots": len(frame),
                    "assignments": assignments,
                    "source_cell": "网页排班",
                }
            )
    result = pd.DataFrame.from_records(rows, columns=BLOCK_COLUMNS)
    if not result.empty:
        result["date"] = pd.to_datetime(result["date"])
    return result


def build_horizontal_grid(
    date_grids: Mapping[dt.date, pd.DataFrame],
) -> tuple[pd.DataFrame, dict[dt.date, dict[str, str]]]:
    """Place every date side by side while sharing one fixed time column."""

    if not date_grids:
        return pd.DataFrame(columns=[TIME_COLUMN, START_MINUTES_COLUMN]), {}

    first_frame = next(iter(date_grids.values()))
    horizontal = first_frame[[TIME_COLUMN, START_MINUTES_COLUMN]].copy()
    horizontal = horizontal.sort_values(START_MINUTES_COLUMN, kind="stable").reset_index(
        drop=True
    )
    starts = horizontal[START_MINUTES_COLUMN]
    date_columns: dict[dt.date, dict[str, str]] = {}

    for date_index, (schedule_date, frame) in enumerate(sorted(date_grids.items())):
        roles = [
            str(column)
            for column in frame.columns
            if column not in {TIME_COLUMN, START_MINUTES_COLUMN}
        ]
        values_by_start = frame.set_index(START_MINUTES_COLUMN)
        fields: dict[str, str] = {}
        for role_index, role in enumerate(roles):
            field = f"schedule_{date_index}_{role_index}"
            fields[field] = role
            horizontal[field] = starts.map(values_by_start[role]).fillna("")
        date_columns[schedule_date] = fields

    return horizontal, date_columns


def horizontal_grid_to_daily_grids(
    horizontal: pd.DataFrame,
    templates: Mapping[dt.date, pd.DataFrame],
    date_columns: Mapping[dt.date, Mapping[str, str]],
) -> dict[dt.date, pd.DataFrame]:
    """Apply edits from a horizontal grid back to its per-date grid model."""

    edited = horizontal.copy()
    edited[START_MINUTES_COLUMN] = pd.to_numeric(
        edited[START_MINUTES_COLUMN], errors="coerce"
    )
    edited = edited.dropna(subset=[START_MINUTES_COLUMN]).copy()
    edited[START_MINUTES_COLUMN] = edited[START_MINUTES_COLUMN].astype(int)
    edited = edited.drop_duplicates(START_MINUTES_COLUMN, keep="last").set_index(
        START_MINUTES_COLUMN
    )

    result: dict[dt.date, pd.DataFrame] = {}
    for schedule_date, template in sorted(templates.items()):
        frame = template.copy()
        for field, role in date_columns.get(schedule_date, {}).items():
            if field not in edited:
                continue
            values = edited[field]
            frame[role] = frame[START_MINUTES_COLUMN].map(values).fillna("")
        result[schedule_date] = frame
    return result


def infer_time_step(records: pd.DataFrame) -> int:
    """Infer a full-day grid interval while never becoming coarser than one hour."""

    values = [60, 24 * 60]
    for row in records.itertuples(index=False):
        start = int(row.start_minutes)
        end = int(row.end_minutes)
        if end <= start:
            end += 24 * 60
        values.extend((start % (24 * 60), end % (24 * 60), end - start))
    positive_values = [abs(value) for value in values if value]
    return max(1, math.gcd(*positive_values))


def format_time_slot(start_minutes: int, end_minutes: int) -> str:
    return f"{_format_clock(start_minutes)}-{_format_clock(end_minutes)}"


def _format_clock(minutes: int) -> str:
    if minutes == 24 * 60:
        return "24:00"
    hours, minute = divmod(minutes % (24 * 60), 60)
    return f"{hours:02d}:{minute:02d}"


def _empty_daily_grid(roles: list[str], step_minutes: int) -> pd.DataFrame:
    starts = list(range(0, 24 * 60, step_minutes))
    data: dict[str, list[object]] = {
        TIME_COLUMN: [
            format_time_slot(start, min(start + step_minutes, 24 * 60))
            for start in starts
        ]
    }
    data.update({role: [""] * len(starts) for role in roles})
    data[START_MINUTES_COLUMN] = starts
    return pd.DataFrame(data)


def _roles_by_team(
    records: pd.DataFrame,
    blocks: pd.DataFrame,
) -> dict[str, list[str]]:
    roles: dict[str, list[str]] = {}
    for row in blocks.itertuples(index=False):
        team_roles = roles.setdefault(str(row.team), [])
        for role in str(row.roles).split("、"):
            role = role.strip()
            if role and role not in team_roles:
                team_roles.append(role)
    for row in records.itertuples(index=False):
        team_roles = roles.setdefault(str(row.team), [])
        role = str(row.role).strip()
        if role and role not in team_roles:
            team_roles.append(role)
    return roles


def _dates_by_team(
    records: pd.DataFrame,
    blocks: pd.DataFrame,
) -> dict[str, list[dt.date]]:
    dates: dict[str, list[dt.date]] = {}
    for frame in (blocks, records):
        for row in frame.itertuples(index=False):
            team_dates = dates.setdefault(str(row.team), [])
            schedule_date = pd.Timestamp(row.date).date()
            if schedule_date not in team_dates:
                team_dates.append(schedule_date)
    return dates


def _clean_cell(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()
