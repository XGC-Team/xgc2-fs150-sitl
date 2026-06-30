#!/usr/bin/env python3
"""Generate the FS150 RViz URDF from the package-owned Gazebo SDF."""

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


PKG_NAME = "gazebo_sim_fs150_sitl"
SCRIPT_PATH = Path(__file__).resolve()


def package_root():
    if SCRIPT_PATH.parent.name == "scripts":
        return SCRIPT_PATH.parents[1]
    try:
        import rospkg

        return Path(rospkg.RosPack().get_path(PKG_NAME)).resolve()
    except Exception:
        pass
    for parent in SCRIPT_PATH.parents:
        candidate = parent / "share" / PKG_NAME
        if candidate.exists():
            return candidate.resolve()
    return SCRIPT_PATH.parents[1]


PKG_ROOT = package_root()
DEFAULT_SDF = PKG_ROOT / "models" / "fs150" / "iris.sdf"
DEFAULT_URDF = PKG_ROOT / "urdf" / "fs150.urdf"


def sanitize_name(name):
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", (name or "").strip().lstrip("/"))
    cleaned = cleaned.strip("_")
    return cleaned or "link"


def parse_pose(text):
    values = [0.0] * 6
    if text:
        parts = text.split()
        for idx, value in enumerate(parts[:6]):
            try:
                values[idx] = float(value)
            except ValueError:
                values[idx] = 0.0
    return values


def pose_text(values):
    return " ".join(f"{value:.9g}" for value in values[:3]), " ".join(f"{value:.9g}" for value in values[3:6])


def pose_is_zero(values):
    return all(abs(value) < 1.0e-12 for value in values)


def child_text(element, name, default=""):
    child = element.find(name)
    return child.text.strip() if child is not None and child.text else default


def add_origin(parent, pose):
    xyz, rpy = pose_text(pose)
    ET.SubElement(parent, "origin", {"xyz": xyz, "rpy": rpy})


def add_geometry(parent, sdf_geometry):
    if sdf_geometry is None:
        return False
    geometry = ET.SubElement(parent, "geometry")
    mesh = sdf_geometry.find("mesh")
    if mesh is not None:
        uri = child_text(mesh, "uri")
        if not uri:
            parent.remove(geometry)
            return False
        attrs = {"filename": resolve_mesh_uri(uri)}
        scale = child_text(mesh, "scale")
        if scale:
            attrs["scale"] = scale
        ET.SubElement(geometry, "mesh", attrs)
        return True
    box = sdf_geometry.find("box")
    if box is not None:
        size = child_text(box, "size")
        if size:
            ET.SubElement(geometry, "box", {"size": size})
            return True
    cylinder = sdf_geometry.find("cylinder")
    if cylinder is not None:
        radius = child_text(cylinder, "radius")
        length = child_text(cylinder, "length")
        if radius and length:
            ET.SubElement(geometry, "cylinder", {"radius": radius, "length": length})
            return True
    sphere = sdf_geometry.find("sphere")
    if sphere is not None:
        radius = child_text(sphere, "radius")
        if radius:
            ET.SubElement(geometry, "sphere", {"radius": radius})
            return True
    parent.remove(geometry)
    return False


def resolve_mesh_uri(uri):
    if uri.startswith("model://fs150/"):
        rel = uri[len("model://fs150/") :]
        return f"package://{PKG_NAME}/models/fs150/{rel}"
    if uri.startswith("model://iris/"):
        rel = uri[len("model://iris/") :]
        return f"package://{PKG_NAME}/models/fs150/{rel}"
    if uri.startswith("file://") or uri.startswith("package://"):
        return uri
    return uri


def material_rgba(sdf_material):
    if sdf_material is None:
        return None
    diffuse = child_text(sdf_material, "diffuse")
    if diffuse:
        return diffuse
    ambient = child_text(sdf_material, "ambient")
    if ambient:
        return ambient
    script_name = child_text(sdf_material.find("script"), "name") if sdf_material.find("script") is not None else ""
    if script_name == "Gazebo/Blue":
        return "0.1 0.2 0.9 1"
    if script_name == "Gazebo/DarkGrey":
        return "0.12 0.12 0.12 1"
    if script_name == "Gazebo/Black":
        return "0.02 0.02 0.02 1"
    return None


def add_visual(urdf_link, sdf_visual, prefix, link_name):
    visual = ET.SubElement(urdf_link, "visual", {"name": sanitize_name(sdf_visual.get("name", "visual"))})
    add_origin(visual, parse_pose(child_text(sdf_visual, "pose")))
    if not add_geometry(visual, sdf_visual.find("geometry")):
        urdf_link.remove(visual)
        return False
    rgba = material_rgba(sdf_visual.find("material"))
    if rgba:
        material = ET.SubElement(visual, "material", {"name": f"{prefix}{link_name}_mat"})
        ET.SubElement(material, "color", {"rgba": rgba})
    return True


def add_collision_as_visual(urdf_link, sdf_collision, prefix, link_name):
    visual = ET.SubElement(urdf_link, "visual", {"name": sanitize_name(sdf_collision.get("name", "collision_visual"))})
    add_origin(visual, parse_pose(child_text(sdf_collision, "pose")))
    if not add_geometry(visual, sdf_collision.find("geometry")):
        urdf_link.remove(visual)
        return False
    material = ET.SubElement(visual, "material", {"name": f"{prefix}{link_name}_collision_mat"})
    ET.SubElement(material, "color", {"rgba": "0.45 0.45 0.45 1"})
    return True


def add_link(robot, sdf_link, prefix):
    raw_name = sdf_link.get("name", "")
    link_name = sanitize_name(raw_name)
    urdf_link = ET.SubElement(robot, "link", {"name": f"{prefix}{link_name}"})
    has_visual = False
    for sdf_visual in sdf_link.findall("visual"):
        has_visual = add_visual(urdf_link, sdf_visual, prefix, link_name) or has_visual
    if not has_visual:
        for sdf_collision in sdf_link.findall("collision"):
            if add_collision_as_visual(urdf_link, sdf_collision, prefix, link_name):
                break
    return link_name, parse_pose(child_text(sdf_link, "pose"))


def add_joint(robot, sdf_joint, prefix, link_poses):
    child = sanitize_name(child_text(sdf_joint, "child"))
    parent = sanitize_name(child_text(sdf_joint, "parent", "base_link"))
    joint_name = sanitize_name(sdf_joint.get("name", f"{parent}_{child}_joint"))
    joint = ET.SubElement(robot, "joint", {"name": f"{prefix}{joint_name}", "type": "fixed"})
    ET.SubElement(joint, "parent", {"link": f"{prefix}{parent}"})
    ET.SubElement(joint, "child", {"link": f"{prefix}{child}"})
    joint_pose = parse_pose(child_text(sdf_joint, "pose"))
    add_origin(joint, link_poses.get(child, joint_pose) if pose_is_zero(joint_pose) else joint_pose)


def add_included_model_link(robot, sdf_include, prefix, link_poses):
    include_name = child_text(sdf_include, "name")
    if not include_name:
        return
    link_name = sanitize_name(f"{include_name}_link")
    if link_name in link_poses:
        return
    urdf_link = ET.SubElement(robot, "link", {"name": f"{prefix}{link_name}"})
    model_name = ""
    uri = child_text(sdf_include, "uri")
    if uri.startswith("model://"):
        model_name = sanitize_name(uri[len("model://") :].split("/", 1)[0])
    if model_name:
        included_sdf = PKG_ROOT / "models" / model_name / f"{model_name}.sdf"
        if included_sdf.exists():
            included_root = ET.parse(included_sdf).getroot()
            included_model = included_root.find("model")
            included_link = included_model.find("link") if included_model is not None else None
            if included_link is not None:
                has_visual = False
                for sdf_visual in included_link.findall("visual"):
                    has_visual = add_visual(urdf_link, sdf_visual, prefix, link_name) or has_visual
                if not has_visual:
                    for sdf_collision in included_link.findall("collision"):
                        if add_collision_as_visual(urdf_link, sdf_collision, prefix, link_name):
                            break
    link_poses[link_name] = parse_pose(child_text(sdf_include, "pose"))


def indent(element, level=0):
    pad = "\n" + level * "  "
    if len(element):
        if not element.text or not element.text.strip():
            element.text = pad + "  "
        for child in element:
            indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = pad
    if level and (not element.tail or not element.tail.strip()):
        element.tail = pad


def generate_urdf(sdf_path, prefix):
    tree = ET.parse(sdf_path)
    sdf_root = tree.getroot()
    model = sdf_root.find("model")
    if model is None:
        raise RuntimeError(f"no <model> in {sdf_path}")
    robot = ET.Element("robot", {"name": f"{prefix}fs150"})
    link_poses = {}
    for sdf_link in model.findall("link"):
        link_name, link_pose = add_link(robot, sdf_link, prefix)
        link_poses[link_name] = link_pose
    for sdf_include in model.findall("include"):
        add_included_model_link(robot, sdf_include, prefix, link_poses)
    joint_children = set()
    for sdf_joint in model.findall("joint"):
        child = sanitize_name(child_text(sdf_joint, "child"))
        joint_children.add(child)
        add_joint(robot, sdf_joint, prefix, link_poses)
    for link_name, link_pose in link_poses.items():
        if link_name != "base_link" and link_name not in joint_children:
            joint = ET.SubElement(robot, "joint", {"name": f"{prefix}base_to_{link_name}", "type": "fixed"})
            ET.SubElement(joint, "parent", {"link": f"{prefix}base_link"})
            ET.SubElement(joint, "child", {"link": f"{prefix}{link_name}"})
            add_origin(joint, link_pose)
    indent(robot)
    return ET.tostring(robot, encoding="unicode") + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdf", default=str(DEFAULT_SDF), help="input FS150 SDF path")
    parser.add_argument("--output", default="", help="output URDF path")
    parser.add_argument("--prefix", nargs="?", const="", default="", help="optional link and joint prefix")
    parser.add_argument("--print", action="store_true", help="print URDF to stdout")
    args = parser.parse_args()

    sdf_path = Path(args.sdf).expanduser().resolve()
    urdf = generate_urdf(sdf_path, sanitize_name(args.prefix) + "_" if args.prefix and not args.prefix.endswith("_") else args.prefix)
    if args.print or not args.output:
        sys.stdout.write(urdf)
    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(urdf, encoding="utf-8")


if __name__ == "__main__":
    main()
