#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

IRIS_MOTOR_CONSTANT = 5.84e-06
IRIS_REFERENCE_HOVER_THRUST = 0.706963405
FS150_TARGET_HOVER_THRUST = 0.30
FS150_TOTAL_MASS = 0.310
FS150_BASE_MASS = 0.260
IRIS_BASE_MASS = 1.5
IRIS_BASE_INERTIA = (0.029125, 0.029125, 0.055225)
FS150_EQUIVALENT_INERTIA_SCALE = 0.35
FS150_BODY_COLLISION_SIZE = (0.47, 0.47, 0.11)
FS150_BODY_VISUAL_POSE = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
FS150_BODY_VISUAL_SCALE = (1.0, 1.0, 1.0)
FS150_ROTOR_POSES = {
    "rotor_0": (0.13, -0.22, 0.023, 0.0, 0.0, 0.0),
    "rotor_1": (-0.13, 0.2, 0.023, 0.0, 0.0, 0.0),
    "rotor_2": (0.13, 0.22, 0.023, 0.0, 0.0, 0.0),
    "rotor_3": (-0.13, -0.2, 0.023, 0.0, 0.0, 0.0),
}
FS150_ROTOR_Z = 0.023
FS150_ROTOR_MASS = 0.005
IRIS_ROTOR_INERTIA = (9.75e-07, 0.000273104, 0.000274004)
FS150_ROTOR_INERTIA = tuple(
    value * FS150_EQUIVALENT_INERTIA_SCALE for value in IRIS_ROTOR_INERTIA
)
FS150_PROP_RADIUS = 0.128
FS150_PROP_COLLISION_RADIUS = FS150_PROP_RADIUS
FS150_PROP_LENGTH = 0.005
FS150_PROP_VISUAL_SCALE = (1.0, 1.0, 1.0)
FS150_PROP_VISUAL_POSE = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
FS150_GPS_POSE = (0.1, 0.0, 0.0, 0.0, 0.0, 0.0)
# Hover-test correction from the total-mass scaled FS150 model. Further
# correction should use
# motorConstant_next = motorConstant_current * (hover_thrust / 0.30)^2.
FS150_MOTOR_CONSTANT = 5.33969944334e-06
FS150_MOMENT_CONSTANT = 0.06
FS150_MOTOR_TIME_CONSTANT_UP = 0.006
FS150_MOTOR_TIME_CONSTANT_DOWN = 0.012
FS150_ROTOR_DRAG_COEFFICIENT = 2e-05
FS150_ROLLING_MOMENT_COEFFICIENT = 1e-07


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
        fs150_root = _rospack_find("gazebo_sim_fs150_sitl")
        yield os.path.join(fs150_root, "models", "fs150", "iris.sdf")
    except subprocess.CalledProcessError:
        pass

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
        "could not find FS150/PX4 iris.sdf; checked: %s" % ", ".join(checked)
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


def _set_text(elem, text):
    elem.text = "{:.12g}".format(float(text))


def _set_vector(elem, values):
    elem.text = " ".join("{:.12g}".format(float(value)) for value in values)


def _scaled_iris_base_inertia(mass):
    ratio = float(mass) / IRIS_BASE_MASS
    return tuple(
        value * ratio * FS150_EQUIVALENT_INERTIA_SCALE
        for value in IRIS_BASE_INERTIA
    )


def _patch_motor_model(
    root,
    motor_constant,
    moment_constant,
    time_constant_up=FS150_MOTOR_TIME_CONSTANT_UP,
    time_constant_down=FS150_MOTOR_TIME_CONSTANT_DOWN,
    rotor_drag_coefficient=FS150_ROTOR_DRAG_COEFFICIENT,
    rolling_moment_coefficient=FS150_ROLLING_MOMENT_COEFFICIENT,
):
    report = []
    motor_count = 0
    moment_count = 0
    time_up_count = 0
    time_down_count = 0
    rotor_drag_count = 0
    rolling_moment_count = 0
    for plugin in root.iter("plugin"):
        motor = plugin.find("motorConstant")
        if motor is not None:
            _set_text(motor, motor_constant)
            motor_count += 1
        moment = plugin.find("momentConstant")
        if moment is not None:
            _set_text(moment, moment_constant)
            moment_count += 1
        time_up = plugin.find("timeConstantUp")
        if time_up is not None:
            _set_text(time_up, time_constant_up)
            time_up_count += 1
        time_down = plugin.find("timeConstantDown")
        if time_down is not None:
            _set_text(time_down, time_constant_down)
            time_down_count += 1
        rotor_drag = plugin.find("rotorDragCoefficient")
        if rotor_drag is not None:
            _set_text(rotor_drag, rotor_drag_coefficient)
            rotor_drag_count += 1
        rolling_moment = plugin.find("rollingMomentCoefficient")
        if rolling_moment is not None:
            _set_text(rolling_moment, rolling_moment_coefficient)
            rolling_moment_count += 1
    report.append(("motorConstant", motor_count))
    report.append(("momentConstant", moment_count))
    report.append(("timeConstantUp", time_up_count))
    report.append(("timeConstantDown", time_down_count))
    report.append(("rotorDragCoefficient", rotor_drag_count))
    report.append(("rollingMomentCoefficient", rolling_moment_count))
    return report


def _patch_body_geometry(root):
    report = []
    collision_count = 0
    visual_count = 0
    for link in root.iter("link"):
        if link.attrib.get("name") != "base_link":
            continue
        for collision in link.iter("collision"):
            if collision.attrib.get("name") != "base_link_inertia_collision":
                continue
            size = collision.find("./geometry/box/size")
            if size is not None:
                _set_vector(size, FS150_BODY_COLLISION_SIZE)
                collision_count += 1
        existing_visuals = list(link.findall("visual"))
        visual = next((v for v in existing_visuals if v.attrib.get("name") == "base_link_inertia_visual"), None)
        for candidate in existing_visuals:
            if candidate is not visual:
                link.remove(candidate)
        if visual is None:
            visual = ET.SubElement(link, "visual", {"name": "base_link_inertia_visual"})
            material = ET.SubElement(visual, "material")
            ET.SubElement(material, "ambient").text = "0.42 0.35 0.05 1"
            ET.SubElement(material, "diffuse").text = "0.84 0.71 0.10 1"
            ET.SubElement(material, "specular").text = "0.05 0.04 0.02 1"
            ET.SubElement(material, "emissive").text = "0 0 0 1"
        pose = visual.find("pose")
        if pose is None:
            pose = ET.Element("pose")
            visual.insert(0, pose)
        _set_vector(pose, FS150_BODY_VISUAL_POSE)
        geometry = visual.find("geometry")
        if geometry is None:
            geometry = ET.SubElement(visual, "geometry")
        for child in list(geometry):
            geometry.remove(child)
        mesh = ET.SubElement(geometry, "mesh")
        ET.SubElement(mesh, "scale").text = " ".join("{:.12g}".format(value) for value in FS150_BODY_VISUAL_SCALE)
        ET.SubElement(mesh, "uri").text = "model://fs150/meshes/iris.stl"
        visual_count += 1
    report.append(("base_link collision size", collision_count))
    report.append(("base_link mesh visual scale", visual_count))
    return report


def _patch_body_mass(root, body_mass):
    target_mass = FS150_BASE_MASS if body_mass is None else float(body_mass)
    ixx, iyy, izz = _scaled_iris_base_inertia(target_mass)

    for link in root.iter("link"):
        if link.attrib.get("name") != "base_link":
            continue
        inertial = link.find("inertial")
        if inertial is None:
            break
        mass = inertial.find("mass")
        inertia = inertial.find("inertia")
        if mass is None or inertia is None:
            break

        _set_text(mass, target_mass)
        values = {
            "ixx": ixx,
            "iyy": iyy,
            "izz": izz,
            "ixy": 0.0,
            "ixz": 0.0,
            "iyz": 0.0,
        }
        for tag, value in values.items():
            elem = inertia.find(tag)
            if elem is not None:
                _set_text(elem, value)
        return [("base_link mass", 1), ("base_link equivalent iris inertia", 1)]

    raise RuntimeError("base_link inertial block not found in source SDF")


def _patch_rotor_model(root):
    pose_count = 0
    mass_count = 0
    inertia_count = 0
    collision_count = 0
    visual_count = 0
    visual_pose_count = 0
    for link in root.iter("link"):
        name = link.attrib.get("name")
        if name not in FS150_ROTOR_POSES:
            continue
        pose = link.find("pose")
        if pose is not None:
            _set_vector(pose, FS150_ROTOR_POSES[name])
            pose_count += 1

        inertial = link.find("inertial")
        if inertial is not None:
            mass = inertial.find("mass")
            if mass is not None:
                _set_text(mass, FS150_ROTOR_MASS)
                mass_count += 1
            inertia = inertial.find("inertia")
            if inertia is not None:
                values = {
                    "ixx": FS150_ROTOR_INERTIA[0],
                    "iyy": FS150_ROTOR_INERTIA[1],
                    "izz": FS150_ROTOR_INERTIA[2],
                    "ixy": 0.0,
                    "ixz": 0.0,
                    "iyz": 0.0,
                }
                for tag, value in values.items():
                    elem = inertia.find(tag)
                    if elem is not None:
                        _set_text(elem, value)
                inertia_count += 1

        for collision in link.iter("collision"):
            cylinder = collision.find("./geometry/cylinder")
            if cylinder is None:
                continue
            length = cylinder.find("length")
            radius = cylinder.find("radius")
            if length is not None and radius is not None:
                _set_text(length, FS150_PROP_LENGTH)
                _set_text(radius, FS150_PROP_COLLISION_RADIUS)
                collision_count += 1

        for visual in link.iter("visual"):
            pose = visual.find("pose")
            if pose is None:
                pose = ET.Element("pose")
                visual.insert(0, pose)
            _set_vector(pose, FS150_PROP_VISUAL_POSE)
            visual_pose_count += 1
            scale = visual.find("./geometry/mesh/scale")
            if scale is not None:
                _set_vector(scale, FS150_PROP_VISUAL_SCALE)
                visual_count += 1

    return [
        ("rotor pose", pose_count),
        ("rotor mass", mass_count),
        ("rotor inertia", inertia_count),
        ("rotor collision cylinder", collision_count),
        ("rotor visual pose", visual_pose_count),
        ("rotor visual scale", visual_count),
    ]


def _patch_gps_pose(root):
    pose_count = 0
    for include in root.iter("include"):
        name = include.find("name")
        if name is None or (name.text or "").strip() != "gps0":
            continue
        pose = include.find("pose")
        if pose is None:
            pose = ET.SubElement(include, "pose")
        _set_vector(pose, FS150_GPS_POSE)
        pose_count += 1
    return [("gps0 pose", pose_count)]


def _indent(elem, level=0):
    spaces = "\n" + level * "  "
    child_spaces = "\n" + (level + 1) * "  "
    children = list(elem)
    if children:
        if not elem.text or not elem.text.strip():
            elem.text = child_spaces
        for child in children:
            _indent(child, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = spaces
    elif level and (not elem.tail or not elem.tail.strip()):
        elem.tail = spaces


def render_indoor_sdf(
    base_sdf,
    strip_gps=False,
    strip_mag=False,
    strip_baro=False,
    motor_constant=FS150_MOTOR_CONSTANT,
    moment_constant=FS150_MOMENT_CONSTANT,
    body_mass=None,
):
    tree = ET.parse(base_sdf)
    root = tree.getroot()
    report = []
    report.extend(_patch_body_geometry(root))
    report.extend(_patch_rotor_model(root))
    report.extend(_patch_gps_pose(root))
    report.extend(_patch_motor_model(root, motor_constant, moment_constant))
    report.extend(_patch_body_mass(root, body_mass))
    if strip_gps:
        report.append(("gps include gps0", len(_remove_include_by_name(root, "gps0"))))
        report.append(("gps joint gps0_joint", len(_remove_joint_by_name(root, "gps0_joint"))))
    if strip_mag:
        report.append(("plugin magnetometer_plugin", len(_remove_named_plugin(root, "magnetometer_plugin"))))
        report.append(("mavlink_interface magSubTopic", len(_remove_plugin_tag(root, "mavlink_interface", "magSubTopic"))))
    if strip_baro:
        report.append(("plugin barometer_plugin", len(_remove_named_plugin(root, "barometer_plugin"))))
        report.append(("mavlink_interface baroSubTopic", len(_remove_plugin_tag(root, "mavlink_interface", "baroSubTopic"))))
    _indent(root)
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
    parser = argparse.ArgumentParser(description="Render an indoor FS150 SDF from an FS150/PX4 iris SDF.")
    parser.add_argument("--base-sdf", default=None,
                        help="Source SDF. Defaults to gazebo_sim_fs150_sitl/models/fs150/iris.sdf when available.")
    parser.add_argument("--output", default=default_output_path(), help="Output SDF path.")
    parser.add_argument("--strip-gps", type=_bool_arg, default=False)
    parser.add_argument("--strip-mag", type=_bool_arg, default=False)
    parser.add_argument("--strip-baro", type=_bool_arg, default=False)
    parser.add_argument("--motor-constant", type=float, default=FS150_MOTOR_CONSTANT,
                        help="Gazebo motor thrust coefficient. Default is calibrated from measured FS150 hover throttle.")
    parser.add_argument("--moment-constant", type=float, default=FS150_MOMENT_CONSTANT)
    parser.add_argument("--body-mass", type=float, default=None,
                        help="Optional base_link mass override. Defaults to FS150_BASE_MASS with cuboid inertia.")
    parser.add_argument("--print-path", action="store_true", help="Print only the output path on stdout.")
    args = parser.parse_args()

    base_sdf = resolve_base_sdf(args.base_sdf)
    sdf, report = render_indoor_sdf(
        base_sdf,
        args.strip_gps,
        args.strip_mag,
        args.strip_baro,
        args.motor_constant,
        args.moment_constant,
        args.body_mass,
    )
    write_atomic(args.output, sdf)

    if args.print_path:
        print(args.output)
    else:
        print("rendered: %s" % args.output)
        print("base_sdf: %s" % base_sdf)
        for label, count in report:
            print("updated %d x %s" % (count, label))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print("failed to resolve ROS package: %s" % exc, file=sys.stderr)
        raise SystemExit(1)
