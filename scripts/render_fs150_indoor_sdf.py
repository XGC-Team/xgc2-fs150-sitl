#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def _bool_arg(value):
    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise argparse.ArgumentTypeError("expected boolean value, got %r" % value)


def _rospack_find(package):
    return subprocess.check_output(["rospack", "find", package], text=True).strip()


def default_base_sdf():
    return resolve_base_sdf(None)


def default_output_path():
    return os.path.join(os.path.expanduser("~"), ".xgc2", "fs150_sitl", "iris_indoor.sdf")


def _candidate_base_sdfs(preferred):
    if preferred:
        yield preferred

    try:
        px4_root = _rospack_find("gazebo_sim_px4_1_12")
        yield os.path.join(px4_root, "models", "iris", "iris.sdf")
    except subprocess.CalledProcessError:
        pass

    ros_distro = os.environ.get("ROS_DISTRO", "noetic")
    yield os.path.join("/opt", "ros", ros_distro, "share", "gazebo_sim_px4_1_12", "models", "iris", "iris.sdf")

    for prefix in os.environ.get("CMAKE_PREFIX_PATH", "").split(os.pathsep):
        if prefix:
            yield os.path.join(prefix, "share", "gazebo_sim_px4_1_12", "models", "iris", "iris.sdf")


def resolve_base_sdf(preferred):
    seen = set()
    checked = []
    for candidate in _candidate_base_sdfs(preferred):
        candidate = os.path.abspath(os.path.expanduser(candidate))
        if candidate in seen:
            continue
        seen.add(candidate)
        checked.append(candidate)
        if os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError(
        "could not find PX4 1.12 iris.sdf; checked: %s" % ", ".join(checked)
    )


def _remove_children(parent, predicate):
    removed = []
    for child in list(parent):
        if predicate(child):
            parent.remove(child)
            removed.append(child)
    return removed


def _remove_named_plugin(root, plugin_name):
    removed = []
    for parent in root.iter():
        removed.extend(
            _remove_children(
                parent,
                lambda child: child.tag == "plugin"
                and child.attrib.get("name") == plugin_name,
            )
        )
    return removed


def _remove_include_by_name(root, include_name):
    removed = []
    for parent in root.iter():
        removed.extend(
            _remove_children(
                parent,
                lambda child: child.tag == "include"
                and child.findtext("name") == include_name,
            )
        )
    return removed


def _remove_joint_by_name(root, joint_name):
    removed = []
    for parent in root.iter():
        removed.extend(
            _remove_children(
                parent,
                lambda child: child.tag == "joint"
                and child.attrib.get("name") == joint_name,
            )
        )
    return removed


def _remove_plugin_tag(root, plugin_name, tag):
    removed = []
    for plugin in root.iter("plugin"):
        if plugin.attrib.get("name") != plugin_name:
            continue
        for elem in list(plugin):
            if elem.tag == tag:
                plugin.remove(elem)
                removed.append(elem)
    return removed


def render_indoor_sdf(base_sdf, strip_gps=True, strip_mag=True, strip_baro=True):
    tree = ET.parse(base_sdf)
    root = tree.getroot()
    report = []
    if strip_gps:
        report.append(("gps include gps0", len(_remove_include_by_name(root, "gps0"))))
        report.append(("gps joint gps0_joint", len(_remove_joint_by_name(root, "gps0_joint"))))
    if strip_mag:
        report.append(("plugin magnetometer_plugin", len(_remove_named_plugin(root, "magnetometer_plugin"))))
        report.append(("mavlink_interface magSubTopic", len(_remove_plugin_tag(root, "mavlink_interface", "magSubTopic"))))
    if strip_baro:
        report.append(("plugin barometer_plugin", len(_remove_named_plugin(root, "barometer_plugin"))))
        report.append(("mavlink_interface baroSubTopic", len(_remove_plugin_tag(root, "mavlink_interface", "baroSubTopic"))))
    return ET.tostring(root, encoding="unicode"), report


def write_atomic(path, content):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".sdf", dir=directory or None)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser(description="Render an indoor FS150 SDF from the installed PX4 1.12 iris SDF.")
    parser.add_argument("--base-sdf", default=None, help="Source SDF. Defaults to gazebo_sim_px4_1_12/models/iris/iris.sdf.")
    parser.add_argument("--output", default=default_output_path(), help="Output SDF path.")
    parser.add_argument("--strip-gps", type=_bool_arg, default=True)
    parser.add_argument("--strip-mag", type=_bool_arg, default=True)
    parser.add_argument("--strip-baro", type=_bool_arg, default=True)
    parser.add_argument("--print-path", action="store_true", help="Print only the output path on stdout.")
    args = parser.parse_args()

    base_sdf = resolve_base_sdf(args.base_sdf)
    sdf, report = render_indoor_sdf(base_sdf, args.strip_gps, args.strip_mag, args.strip_baro)
    write_atomic(args.output, sdf)

    if args.print_path:
        print(args.output)
    else:
        print("rendered: %s" % args.output)
        print("base_sdf: %s" % base_sdf)
        for label, count in report:
            print("removed %d x %s" % (count, label))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print("failed to resolve ROS package: %s" % exc, file=sys.stderr)
        raise SystemExit(1)
