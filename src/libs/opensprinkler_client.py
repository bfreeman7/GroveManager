"""
HTTP client for OpenSprinkler (JSON API).

Password is sent as MD5 hex in the ``pw`` query parameter per device API.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Optional

import requests

_PW_MD5_RE = re.compile(r"^[a-f0-9]{32}$", re.IGNORECASE)


def resolve_opensprinkler_pw_hash(*, password: str = "", password_md5: str = "") -> str:
    """Return lowercase MD5 hex for OpenSprinkler ``pw`` query param."""
    md5 = password_md5.strip()
    if md5:
        if not _PW_MD5_RE.match(md5):
            raise ValueError("OPENSPRINKLER_PW_MD5 must be 32 hex characters")
        return md5.lower()
    plain = password.strip()
    if plain:
        return hashlib.md5(plain.encode()).hexdigest()
    return ""


class OpenSprinklerClient:
    def __init__(
        self,
        base_url: str,
        password: str = "",
        password_md5: str = "",
        timeout_seconds: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._pw_hash = resolve_opensprinkler_pw_hash(password=password, password_md5=password_md5)
        if not self._pw_hash:
            raise ValueError("OpenSprinkler password or password_md5 is required")

    def _params(self, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        out: dict[str, Any] = {"pw": self._pw_hash}
        if extra:
            out.update(extra)
        return out

    def _request(self, path: str, extra_params: Optional[dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        r = requests.get(
            url,
            params=self._params(extra_params),
            timeout=self._timeout,
        )
        r.raise_for_status()
        return r.json()

    def _get_json(self, path: str, extra_params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        data = self._request(path, extra_params)
        if not isinstance(data, dict):
            raise ValueError(f"OpenSprinkler {path} returned non-object JSON")
        return data

    def get_json_all(self) -> dict[str, Any]:
        """
        Combined controller snapshot.

        Prefer GET /ja when firmware supports it; otherwise assemble /jc, /jo, /jn, /js, /jp.
        """
        try:
            return self._get_json("ja")
        except requests.HTTPError as e:
            if e.response is None or e.response.status_code != 404:
                raise
        return {
            "settings": self._get_json("jc"),
            "options": self._get_json("jo"),
            "stations": self._get_json("jn"),
            "status": self._get_json("js"),
            "programs": self._get_json("jp"),
        }

    def change_program(self, params: dict[str, Any]) -> dict[str, Any]:
        """GET /cp — change program data (used by schedule update endpoint)."""
        return self._get_json("cp", params)

    def manual_station(
        self,
        sid: int,
        en: int,
        t: Optional[int] = None,
        qo: Optional[int] = None,
        ssta: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        GET /cm — manual station on/off (for a future UI).

        ``en`` 1 = open, 0 = close. ``t`` duration seconds when opening.
        """
        p: dict[str, Any] = {"sid": sid, "en": en}
        if t is not None:
            p["t"] = t
        if qo is not None:
            p["qo"] = qo
        if ssta is not None:
            p["ssta"] = ssta
        return self._get_json("cm", p)

    def get_run_log(self, hist: int = 7) -> list[Any]:
        """GET /jl — run history (requires device logging enabled)."""
        data = self._request("jl", {"hist": hist})
        if isinstance(data, list):
            return data
        raise ValueError("OpenSprinkler /jl returned unexpected JSON (expected array)")

    def set_logging_enabled(self, lg: int) -> dict[str, Any]:
        """GET /co — enable or disable run history logging (``lg`` 0 or 1)."""
        if lg not in (0, 1):
            raise ValueError("lg must be 0 or 1")
        return self._get_json("co", {"lg": lg})


_SUNRISE_SUNSET_DUR = 65534
_SUNSET_SUNRISE_DUR = 65535
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _format_duration_seconds(sec: int) -> str:
    if sec == _SUNRISE_SUNSET_DUR:
        return "sunrise–sunset"
    if sec == _SUNSET_SUNRISE_DUR:
        return "sunset–sunrise"
    if sec <= 0:
        return ""
    if sec < 60:
        return f"{sec}s"
    m, s = divmod(sec, 60)
    if s == 0 and m % 60 == 0:
        return f"{m // 60}h"
    if s == 0:
        return f"{m}m"
    return f"{m}m {s}s"


_LOG_EVENT_LABELS = {
    "s1": "Sensor 1",
    "s2": "Sensor 2",
    "rd": "Rain delay",
    "fl": "Flow",
    "wl": "Watering level",
}


def _program_label(pid: int, program_names: list[str]) -> str:
    if pid == 0:
        return "Event"
    if pid == 99:
        return "Manual"
    if pid == 254:
        return "Run once"
    idx = pid - 1
    if 0 <= idx < len(program_names):
        return program_names[idx]
    return f"Program {pid}"


def summarize_run_log(
    records: list[Any],
    station_names: list[str],
    program_names: list[str],
) -> list[dict[str, Any]]:
    """Decode /jl records into UI-friendly rows (newest first)."""
    rows: list[dict[str, Any]] = []
    for rec in records:
        if not isinstance(rec, list) or len(rec) < 4:
            continue
        try:
            pid = int(rec[0])
            dur = int(rec[2])
            end = int(rec[3])
        except (TypeError, ValueError):
            continue

        end_iso = datetime.fromtimestamp(end, tz=timezone.utc).isoformat()

        if pid == 0:
            code = str(rec[1])
            rows.append(
                {
                    "kind": "event",
                    "label": _LOG_EVENT_LABELS.get(code, code),
                    "duration_seconds": dur,
                    "duration_label": _format_duration_seconds(dur) or f"{dur}s",
                    "end_epoch": end,
                    "end_iso": end_iso,
                }
            )
            continue

        try:
            sid = int(rec[1])
        except (TypeError, ValueError):
            continue
        station_name = station_names[sid] if sid < len(station_names) else f"Station {sid + 1}"
        rows.append(
            {
                "kind": "run",
                "station_id": sid,
                "station_name": station_name,
                "program_id": pid,
                "program_name": _program_label(pid, program_names),
                "duration_seconds": dur,
                "duration_label": _format_duration_seconds(dur) or f"{dur}s",
                "end_epoch": end,
                "end_iso": end_iso,
            }
        )

    rows.sort(key=lambda r: int(r.get("end_epoch", 0)), reverse=True)
    return rows


def _minutes_to_clock(total_min: int) -> str:
    total_min = int(total_min) % (24 * 60)
    h24, m = divmod(total_min, 60)
    h12 = h24 % 12
    if h12 == 0:
        h12 = 12
    suffix = "AM" if h24 < 12 else "PM"
    return f"{h12}:{m:02d} {suffix}"


def _decode_weekday_line(days0: int) -> str:
    d = int(days0) & 0x7F
    if d == 0:
        return "No weekdays selected"
    if d == 0x7F:
        return "Every day"
    parts = [_WEEKDAYS[i] for i in range(7) if d & (1 << i)]
    return ", ".join(parts) if parts else "Custom days"


def _decode_schedule_line(flag: int, days0: int, days1: int, starts: list) -> str:
    try:
        f = int(flag)
    except (TypeError, ValueError):
        return ""
    day_type = (f >> 4) & 3
    fixed_times = bool(f & 0x40)
    st = [int(x) for x in starts] if isinstance(starts, list) else []

    if day_type == 0:
        day_part = _decode_weekday_line(days0)
    elif day_type == 1:
        day_part = "Single day (interval calendar)"
    elif day_type == 2:
        day_part = f"Monthly on day {int(days0)}"
    else:
        day_part = f"Every {int(days1)}d (offset {int(days0)})"

    if fixed_times and len(st) >= 4:
        clocks = []
        for raw in st[:4]:
            if raw < 0 or (raw & 0x8000):
                continue
            if (raw & 0x6000) == 0:
                clocks.append(_minutes_to_clock(raw & 0xFFFF))
            else:
                clocks.append(f"offset {raw}")
        time_part = ", ".join(clocks) if clocks else "Fixed times"
        return f"{day_part} · {time_part}"

    if len(st) >= 3:
        first, reps, every_m = st[0], st[1], st[2]
        if (first & 0x8000) == 0 and (first & 0x6000) == 0:
            t0 = first & 0xFFFF
            if t0 < 24 * 60:
                base = _minutes_to_clock(t0)
                if reps and every_m:
                    return f"{day_part} · {base}, every {every_m}m × {reps}"
                return f"{day_part} · {base}"
    return day_part


def _watering_line(durations: list, station_names: list[str]) -> tuple[str, int]:
    if not isinstance(durations, list):
        return ("", 0)
    total = 0
    parts: list[str] = []
    for i, raw in enumerate(durations):
        try:
            sec = int(raw)
        except (TypeError, ValueError):
            continue
        if sec <= 0 or sec in (_SUNRISE_SUNSET_DUR, _SUNSET_SUNRISE_DUR):
            if sec in (_SUNRISE_SUNSET_DUR, _SUNSET_SUNRISE_DUR):
                label = station_names[i] if i < len(station_names) else f"Station {i + 1}"
                parts.append(f"{label} ({_format_duration_seconds(sec)})")
            continue
        total += sec
        label = station_names[i] if i < len(station_names) else f"Station {i + 1}"
        parts.append(f"{label} {_format_duration_seconds(sec)}")
    if not parts:
        return ("No station run times", 0)
    tail = f" · {total // 60}m total" if total else ""
    return (" · ".join(parts) + tail, total)


def _summarize_program_row(
    idx: int,
    entry: list,
    station_names: list[str],
) -> Optional[dict[str, Any]]:
    if not isinstance(entry, list) or len(entry) < 6:
        return None
    try:
        flag = int(entry[0])
    except (TypeError, ValueError):
        flag = 0
    days0 = int(entry[1]) if len(entry) > 1 else 0
    days1 = int(entry[2]) if len(entry) > 2 else 0
    starts = entry[3] if isinstance(entry[3], list) else []
    durs = entry[4] if isinstance(entry[4], list) else []
    name = entry[5]
    if not isinstance(name, str):
        name = str(name)
    enabled = bool(flag & 1)
    use_weather = bool(flag & 2)
    schedule = _decode_schedule_line(flag, days0, days1, starts)
    watering, total_sec = _watering_line(durs, station_names)
    return {
        "id": idx,
        "name": name,
        "enabled": enabled,
        "use_weather": use_weather,
        "schedule": schedule,
        "watering": watering,
        "total_watering_seconds": total_sec,
    }


def summarize_json_all(data: dict[str, Any]) -> dict[str, Any]:
    """
    Build a small UI-oriented summary from ``GET /ja`` response.

    Keys follow OpenSprinkler: settings (/jc), stations (/jn), status (/js), programs (/jp).
    """
    settings = data.get("settings") or {}
    options = data.get("options") or {}
    stations_block = data.get("stations") or {}
    status_block = data.get("status") or {}
    programs_block = data.get("programs") or {}

    controller: dict[str, Any] = {}
    if "lg" in options:
        controller["lg"] = options["lg"]
        try:
            controller["logging_enabled"] = bool(int(options["lg"]))
        except (TypeError, ValueError):
            pass
    if "en" in settings:
        controller["en"] = settings["en"]
    if "rd" in settings:
        controller["rd"] = settings["rd"]
    if "devt" in settings:
        controller["devt"] = settings["devt"]
    if "lrun" in settings:
        controller["lrun"] = settings["lrun"]
    if "ps" in settings:
        controller["ps"] = settings["ps"]

    snames = stations_block.get("snames")
    if not isinstance(snames, list):
        snames = []

    sn = status_block.get("sn")
    if not isinstance(sn, list):
        sn = []

    n = max(len(snames), len(sn))
    station_rows = []
    for i in range(n):
        name = snames[i] if i < len(snames) else f"Station {i + 1}"
        if not isinstance(name, str):
            name = str(name)
        on_val = sn[i] if i < len(sn) else 0
        try:
            on = bool(int(on_val))
        except (TypeError, ValueError):
            on = bool(on_val)
        station_rows.append({"id": i, "name": name, "on": on})

    name_list = [str(x) for x in snames]

    pd = programs_block.get("pd")
    program_rows = []
    if isinstance(pd, list):
        for idx, entry in enumerate(pd):
            row = _summarize_program_row(idx, entry, name_list)
            if row:
                program_rows.append(row)

    return {
        "controller": controller,
        "stations": station_rows,
        "programs": program_rows,
    }
