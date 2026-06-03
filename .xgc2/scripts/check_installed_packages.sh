#!/usr/bin/env bash
set -euo pipefail

ROS_DISTRO="${ROS_DISTRO:-noetic}"
source "/opt/ros/${ROS_DISTRO}/setup.bash"

dpkg -s ros-noetic-xgc2-gazebo-sim-fs150-sitl >/dev/null
test "$(rospack find gazebo_sim_fs150_sitl)" = "/opt/ros/${ROS_DISTRO}/share/gazebo_sim_fs150_sitl"
test -x "/opt/ros/${ROS_DISTRO}/lib/gazebo_sim_fs150_sitl/generate_fs150_sitl_params.py"
test -f "/opt/ros/${ROS_DISTRO}/share/gazebo_sim_fs150_sitl/config/generated/fs150-sitl.params"

"/opt/ros/${ROS_DISTRO}/lib/gazebo_sim_fs150_sitl/generate_fs150_sitl_params.py" \
  --source "/opt/ros/${ROS_DISTRO}/share/gazebo_sim_fs150_sitl/config/source/fs150-mav_sys_id4.params" \
  --output /tmp/fs150-sitl.params \
  --selection-report /tmp/fs150-sitl.selection.csv \
  --no-runtime-baseline

grep -q 'MPC_THR_HOVER' /tmp/fs150-sitl.params
grep -q 'EKF2_AID_MASK' /tmp/fs150-sitl.params
grep -q 'SYS_AUTOSTART,4011,6,exclude' /tmp/fs150-sitl.selection.csv
grep -q 'CAL_ACC0_ID' /tmp/fs150-sitl.selection.csv

echo "Installed FS150 SITL package check passed"
