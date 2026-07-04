#!/usr/bin/env python3
"""Generate an FS150-on-iris PX4 SITL parameter overlay.

The source FS150 file is a real-vehicle QGroundControl export.  This script
intentionally keeps only parameters that can be meaningfully applied to a PX4
1.12 iris SITL instance.  Hardware identity, calibration, IO/PWM, RC, serial
port and MAVLink port ownership stay with the simulator runtime.
"""

from __future__ import annotations

import argparse
import csv
import json
import lzma
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_RUNTIME_ROOT = "/opt/ros/noetic/share/px4_sitl_1_12/runtime"


PROFILE_ORDER = ("control", "power", "safety", "estimator_mocap")

PROFILE_RULES: Dict[str, Sequence[Tuple[str, str]]] = {
    "control": (
        ("regex", r"^MC_(ROLL|PITCH)RATE_[PID]$"),
        ("exact", "MPC_THR_HOVER"),
        ("exact", "MPC_USE_HTE"),
        ("exact", "MPC_XY_VEL_D_ACC"),
        ("exact", "MPC_MANTHR_MIN"),
        ("exact", "IMU_DGYRO_CUTOFF"),
        ("exact", "IMU_GYRO_CUTOFF"),
        ("exact", "IMU_INTEG_RATE"),
    ),
    "power": (
        ("exact", "BAT_N_CELLS"),
        ("exact", "BAT_V_CHARGED"),
        ("exact", "BAT_V_EMPTY"),
        ("exact", "BAT_LOW_THR"),
        ("exact", "BAT_CRIT_THR"),
        ("exact", "BAT_EMERGEN_THR"),
        ("exact", "COM_LOW_BAT_ACT"),
    ),
    "safety": (
        ("exact", "COM_DL_LOSS_T"),
        ("exact", "COM_DISARM_LAND"),
        ("exact", "COM_KILL_DISARM"),
        ("exact", "NAV_DLL_ACT"),
    ),
    "estimator_mocap": (
        ("exact", "EKF2_AID_MASK"),
        ("exact", "EKF2_HGT_MODE"),
        ("exact", "EKF2_MAG_TYPE"),
        ("exact", "EKF2_REQ_GPS_H"),
        ("exact", "MAV_ODOM_LP"),
    ),
    "mavlink_rate": (
        ("exact", "MAV_0_RATE"),
    ),
}


EXCLUDE_PATTERNS: Sequence[Tuple[str, str]] = (
    ("airframe/model identity belongs to PX4 SITL runtime", r"^SYS_AUTOSTART$"),
    ("hardware calibration belongs to the Gazebo/SITL sensor model", r"^CAL_"),
    ("board/sensor hardware setup belongs to the simulator", r"^SENS_"),
    ("RC simulation is not part of this wrapper", r"^(RC_|COM_RC_|MAN_)"),
    ("PWM/actuator output mapping belongs to the iris mixer/SDF", r"^(PWM_|PWM_MAIN_|PWM_AUX_|CA_|ACT_|MOT_)"),
    ("serial/GPS/UAVCAN device ownership is not portable in SITL", r"^(SER_|GPS_|UAVCAN|UAVCAN_)"),
    ("MAVLink instance ports and forwarding are injected by the SITL runtime", r"^MAV_.*_(CONFIG|BROADCAST|FORWARD|MODE|RADIO_CTL|REMOTE_PRT|UDP_PRT)$"),
    ("system identity is derived from PX4 instance ID", r"^MAV_SYS_ID$"),
    ("hardware battery ADC scaling is not valid for Gazebo", r"^BAT_(A_PER_V|V_DIV|V_OFFS|MONITOR|SOURCE|CAPACITY)$"),
    ("hardware-specific secondary battery settings are not valid for Gazebo", r"^BAT1_"),
    ("logging/storage policy is not part of the flight-model overlay", r"^(SDLOG_|SYS_LOGGER|LOG_)"),
    ("estimator sensor offsets/calibration belong to the simulated sensor stack", r"^EKF2_(IMU|MAG|GPS|BARO)_.*(BIAS|OFF|SCALE|NOISE)$"),
    ("return-home mission details are intentionally left to the scenario wrapper", r"^(RTL_|NAV_RCL_ACT|NAV_RCL_LT)$"),
)


TYPE_FLOAT = 9
TYPE_INT32 = 6

SITL_OVERRIDES: Sequence[Tuple[str, str, int, str]] = (
    (
        "IMU_GYRO_RATEMAX",
        "800",
        TYPE_INT32,
        "Match the FS150 high-rate raw-IMU test setup; Gazebo still provides HIL_SENSOR at the simulator rate.",
    ),
    (
        "IMU_INTEG_RATE",
        "800",
        TYPE_INT32,
        "Match the FS150 high-rate raw-IMU test setup and avoid the real export's lower 200 Hz integration rate.",
    ),
    (
        "COM_ARM_WO_GPS",
        "1",
        TYPE_INT32,
        "Allow arming without a GPS because FS150 indoor SITL is external-vision aided.",
    ),
    (
        "EKF2_GPS_CHECK",
        "0",
        TYPE_INT32,
        "Disable GPS quality checks because the default FS150 indoor model has no GPS sensor.",
    ),
    (
        "COM_POSCTL_NAVL",
        "0",
        TYPE_INT32,
        "Use Altitude/Manual fallback on position-control navigation loss in the indoor vision workflow.",
    ),
    (
        "COM_TAKEOFF_ACT",
        "0",
        TYPE_INT32,
        "Mirror the real FS150 export: hold on takeoff failure instead of trying to resume Mission.",
    ),
    (
        "NAV_DLL_ACT",
        "2",
        TYPE_INT32,
        "Mirror the real FS150 export: Return on data-link loss.",
    ),
    (
        "NAV_RCL_ACT",
        "2",
        TYPE_INT32,
        "Mirror the real FS150 export: Return on RC loss.",
    ),
    (
        "COM_OBL_ACT",
        "0",
        TYPE_INT32,
        "Mirror the real FS150 export: land on offboard loss.",
    ),
    (
        "COM_RC_IN_MODE",
        "1",
        TYPE_INT32,
        "PX4 SITL has no physical RC receiver; joystick/no-RC checks matches headless simulation.",
    ),
    (
        "COM_RCL_EXCEPT",
        "4",
        TYPE_INT32,
        "Ignore RC loss in Offboard so algorithm tests do not depend on a physical transmitter.",
    ),
    (
        "EKF2_RNG_AID",
        "0",
        TYPE_INT32,
        "Disable rangefinder height aiding so indoor FS150 SITL height remains external-vision only.",
    ),
    (
        "EKF2_TERR_MASK",
        "0",
        TYPE_INT32,
        "Disable range/optical-flow terrain fusion because the indoor FS150 workflow does not use HAGL aiding.",
    ),
)
SITL_OVERRIDE_NAMES = {name for name, _value, _px4_type, _reason in SITL_OVERRIDES}


@dataclass(frozen=True)
class Param:
    name: str
    value: str
    px4_type: int
    source_line: int


@dataclass(frozen=True)
class Decision:
    name: str
    value: str
    px4_type: int
    action: str
    profile: str
    reason: str


def parse_qgc_params(path: Path) -> Dict[str, Param]:
    params: Dict[str, Param] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for lineno, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = re.split(r"\s+", line)
            if len(parts) < 5:
                continue
            name = parts[2]
            value = parts[3]
            try:
                px4_type = int(parts[4])
            except ValueError:
                px4_type = infer_px4_type(value)
            params[name] = Param(name=name, value=value, px4_type=px4_type, source_line=lineno)
    return params


def infer_px4_type(value: str) -> int:
    try:
        number = float(value)
    except ValueError:
        return TYPE_FLOAT
    if number.is_integer() and "." not in value and "e" not in value.lower():
        return TYPE_INT32
    return TYPE_FLOAT


def load_known_runtime_params(runtime_root: Optional[Path]) -> Optional[set]:
    if runtime_root is None:
        return None
    metadata = runtime_root / "parameters.xml"
    if metadata.exists():
        text = metadata.read_text(encoding="utf-8", errors="replace")
        return set(re.findall(r'<parameter[^>]+name="([^"]+)"', text))

    json_metadata = runtime_root / "etc" / "extras" / "parameters.json.xz"
    if json_metadata.exists():
        with lzma.open(json_metadata, "rt", encoding="utf-8", errors="replace") as handle:
            data = json.load(handle)
        return {item["name"] for item in data.get("parameters", []) if "name" in item}

    return None


def match_profile(name: str, profiles: Iterable[str]) -> Tuple[Optional[str], Optional[str]]:
    for profile in profiles:
        for kind, pattern in PROFILE_RULES.get(profile, ()):
            if kind == "exact" and name == pattern:
                return profile, f"matched {profile}:{pattern}"
            if kind == "regex" and re.match(pattern, name):
                return profile, f"matched {profile}:{pattern}"
    return None, None


def excluded_reason(name: str) -> Optional[str]:
    for reason, pattern in EXCLUDE_PATTERNS:
        if re.match(pattern, name):
            return reason
    return None


def classify(
    params: Dict[str, Param],
    profiles: Sequence[str],
    known_runtime_params: Optional[set],
    allow_missing: bool,
) -> List[Decision]:
    decisions: List[Decision] = []
    for name in sorted(params):
        param = params[name]
        if name in SITL_OVERRIDE_NAMES:
            decisions.append(Decision(name, param.value, param.px4_type, "exclude", "", "overridden by FS150 SITL policy"))
            continue

        reason = excluded_reason(name)
        if reason is not None:
            decisions.append(Decision(name, param.value, param.px4_type, "exclude", "", reason))
            continue

        if known_runtime_params is not None and name not in known_runtime_params and not allow_missing:
            decisions.append(Decision(name, param.value, param.px4_type, "exclude", "", "not present in PX4 1.12 runtime metadata"))
            continue

        profile, include_reason = match_profile(name, profiles)
        if profile:
            decisions.append(Decision(name, param.value, param.px4_type, "include", profile, include_reason or "matched profile"))
        else:
            decisions.append(Decision(name, param.value, param.px4_type, "exclude", "", "not selected by FS150 SITL policy"))
    return decisions


def write_param_overlay(path: Path, decisions: Sequence[Decision], vehicle_id: int, component_id: int) -> None:
    included = [decision for decision in decisions if decision.action == "include"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("# FS150 SITL parameter overlay generated by generate_fs150_sitl_params.py\n")
        handle.write("# Keep simulator-owned calibration, airframe, RC, PWM and MAVLink port ownership out of this file.\n")
        handle.write("# Vehicle/component ids are QGC file metadata only; MAV_SYS_ID is injected by PX4 SITL instance ID.\n")
        handle.write("# Vehicle-Id Component-Id Name Value Type\n")
        for decision in included:
            handle.write(f"{vehicle_id}\t{component_id}\t{decision.name}\t{decision.value}\t{decision.px4_type}\n")
        for name, value, px4_type, _reason in SITL_OVERRIDES:
            handle.write(f"{vehicle_id}\t{component_id}\t{name}\t{value}\t{px4_type}\n")


def write_selection_report(path: Path, decisions: Sequence[Decision]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["name", "value", "type", "action", "profile", "reason"])
        for decision in decisions:
            writer.writerow([decision.name, decision.value, decision.px4_type, decision.action, decision.profile, decision.reason])
        for name, value, px4_type, reason in SITL_OVERRIDES:
            writer.writerow([name, value, px4_type, "include", "sitl_override", reason])


def parse_profiles(raw: str, include_mavlink_rate: bool) -> List[str]:
    if raw.strip().lower() == "default":
        profiles = list(PROFILE_ORDER)
    else:
        profiles = [item.strip() for item in raw.split(",") if item.strip()]
    if include_mavlink_rate and "mavlink_rate" not in profiles:
        profiles.append("mavlink_rate")
    unknown = [profile for profile in profiles if profile not in PROFILE_RULES]
    if unknown:
        raise ValueError(f"unknown profile(s): {', '.join(unknown)}")
    return profiles


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate FS150 PX4 SITL parameter overlay.")
    parser.add_argument("--source", default="firmware/fs150-mav_sys_id4.params", help="QGroundControl parameter export from the real FS150.")
    parser.add_argument("--output", default="config/generated/fs150-sitl.params", help="Generated SITL overlay parameter file.")
    parser.add_argument("--selection-report", default="config/generated/fs150-sitl.selection.csv", help="CSV report explaining include/exclude decisions.")
    parser.add_argument("--runtime-root", default=DEFAULT_RUNTIME_ROOT, help="PX4 1.12 runtime root used to reject unknown parameters.")
    parser.add_argument("--no-runtime-baseline", action="store_true", help="Do not require PX4 runtime metadata.")
    parser.add_argument("--allow-missing", action="store_true", help="Allow parameters missing from runtime metadata.")
    parser.add_argument("--profiles", default="default", help="Comma-separated profile names, or 'default'.")
    parser.add_argument("--include-mavlink-rate", action="store_true", help="Also import MAVLink stream-rate tuning while keeping ports/modes runtime-owned.")
    parser.add_argument("--vehicle-id", type=int, default=4, help="QGC metadata vehicle id written to the output file.")
    parser.add_argument("--component-id", type=int, default=1, help="QGC metadata component id written to the output file.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        profiles = parse_profiles(args.profiles, args.include_mavlink_rate)
    except ValueError as exc:
        parser.error(str(exc))

    source = Path(args.source)
    output = Path(args.output)
    selection_report = Path(args.selection_report)
    runtime_root = None if args.no_runtime_baseline else Path(args.runtime_root)

    if not source.exists():
        print(f"source parameter file not found: {source}", file=sys.stderr)
        return 2

    known_runtime_params = load_known_runtime_params(runtime_root)
    if known_runtime_params is None and not args.no_runtime_baseline:
        print(f"warning: PX4 runtime metadata not found under {runtime_root}; continuing without metadata validation", file=sys.stderr)
    if known_runtime_params is not None and not args.allow_missing:
        missing_overrides = [name for name in SITL_OVERRIDE_NAMES if name not in known_runtime_params]
        if missing_overrides:
            print(
                "SITL override parameter(s) missing from PX4 runtime metadata: "
                + ", ".join(sorted(missing_overrides)),
                file=sys.stderr,
            )
            return 2

    params = parse_qgc_params(source)
    decisions = classify(params, profiles, known_runtime_params, args.allow_missing)

    write_param_overlay(output, decisions, args.vehicle_id, args.component_id)
    write_selection_report(selection_report, decisions)

    included = sum(1 for decision in decisions if decision.action == "include")
    excluded = len(decisions) - included
    overrides = len(SITL_OVERRIDES)
    print(f"generated {output}: {included} selected + {overrides} overrides, {excluded} excluded")
    print(f"selection report: {selection_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
