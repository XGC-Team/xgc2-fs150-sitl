#!/usr/bin/env python3
import os
import sys

preferred_prefix, runtime_root, state_root, model_name, instance, parameter_file, *runner_args = sys.argv[1:]
import re
model_name = model_name[1:] if model_name.startswith('/') else model_name
if preferred_prefix != '/opt/ros/noetic' or runtime_root != '/opt/ros/noetic/share/px4_sitl_1_12/runtime':
    raise SystemExit('FS150 requires its installed Noetic/PX4 runtime')
if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,127}', model_name):
    raise SystemExit('invalid FS150 model name')
if not instance.isdecimal() or not 0 <= int(instance) <= 243:
    raise SystemExit('invalid SITL instance')
if os.path.normpath(state_root) != state_root or state_root == '/' or not (os.path.isabs(state_root) or state_root.startswith('~/')):
    raise SystemExit('invalid FS150 state directory')

prefixes = []
for prefix in (
    preferred_prefix,
    os.environ.get("XGC_ROS_PRODUCTS_PREFIX", ""),
    os.environ.get("XGC2_ROS1_PRODUCTS_DEV_ROOT", ""),
    os.path.join(os.path.expanduser("~"), ".local", "xgc2", "ros", "noetic"),
    "/opt/ros/noetic",
):
    if prefix and prefix not in prefixes:
        prefixes.append(prefix)
for entry in os.environ.get("CMAKE_PREFIX_PATH", "").split(os.pathsep):
    if entry and entry not in prefixes:
        prefixes.append(entry)
candidates = []
for prefix in prefixes:
    for pkg in ("px4_sitl_1_12", "gazebo_sim_px4_1_12"):
        path = os.path.join(prefix, "lib", pkg, "run_px4_sitl.sh")
        if path not in candidates:
            candidates.append(path)
runner = next((path for path in candidates if os.access(path, os.X_OK)), "")
if not runner:
    raise SystemExit("run_px4_sitl.sh is not installed in the configured ROS prefix or the user overlay")
if not os.path.isfile(parameter_file):
    # Source-dev: params live under the products prefix, not always rosRuntimePrefix.
    relative = "share/gazebo_sim_fs150_sitl/config/generated/fs150-sitl.params"
    parameter_file = next((os.path.join(prefix, relative) for prefix in prefixes
                           if os.path.isfile(os.path.join(prefix, relative))), parameter_file)
if not os.path.isfile(parameter_file):
    raise SystemExit("FS150 PX4 parameter file is missing: " + parameter_file)
work_dir = os.path.join(os.path.expanduser(state_root), model_name)
argv = [runner, "--runtime-root", runtime_root, "--work-dir", work_dir, "--instance", instance,
        "--script", "etc/init.d-posix/rcS", "--param-file", parameter_file, "--reset-params", "--"] + runner_args
os.execv(runner, argv)
