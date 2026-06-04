#!/usr/bin/env bash
set -euo pipefail

ROS_DISTRO="${ROS_DISTRO:-noetic}"
source "/opt/ros/${ROS_DISTRO}/setup.bash"

dpkg -s ros-noetic-xgc2-gazebo-sim-fs150-sitl >/dev/null
test "$(rospack find gazebo_sim_fs150_sitl)" = "/opt/ros/${ROS_DISTRO}/share/gazebo_sim_fs150_sitl"
test -x "/opt/ros/${ROS_DISTRO}/lib/gazebo_sim_fs150_sitl/generate_fs150_sitl_params.py"
test -x "/opt/ros/${ROS_DISTRO}/lib/gazebo_sim_fs150_sitl/render_fs150_indoor_sdf.py"
test -f "/opt/ros/${ROS_DISTRO}/share/gazebo_sim_fs150_sitl/config/generated/fs150-sitl.params"
test -f "/opt/ros/${ROS_DISTRO}/share/gazebo_sim_fs150_sitl/launch/fs150.launch"

cat >/tmp/fs150-test-base.sdf <<'EOF'
<sdf version="1.6">
  <model name="iris">
    <include><uri>model://gps</uri><name>gps0</name></include>
    <joint name="gps0_joint" type="fixed"/>
    <plugin name="magnetometer_plugin" filename="libgazebo_magnetometer_plugin.so"/>
    <plugin name="barometer_plugin" filename="libgazebo_barometer_plugin.so"/>
    <plugin name="mavlink_interface" filename="libgazebo_mavlink_interface.so">
      <magSubTopic>/mag</magSubTopic>
      <baroSubTopic>/baro</baroSubTopic>
    </plugin>
  </model>
</sdf>
EOF
"/opt/ros/${ROS_DISTRO}/lib/gazebo_sim_fs150_sitl/render_fs150_indoor_sdf.py" \
  --base-sdf /tmp/fs150-test-base.sdf \
  --output /tmp/fs150-test-indoor.sdf >/tmp/fs150-test-render.log
! grep -q '^removed ' /tmp/fs150-test-render.log
grep -q 'magnetometer_plugin' /tmp/fs150-test-indoor.sdf
grep -q 'barometer_plugin' /tmp/fs150-test-indoor.sdf
grep -q 'magSubTopic' /tmp/fs150-test-indoor.sdf
grep -q 'baroSubTopic' /tmp/fs150-test-indoor.sdf

"/opt/ros/${ROS_DISTRO}/lib/gazebo_sim_fs150_sitl/render_fs150_indoor_sdf.py" \
  --base-sdf /tmp/fs150-test-base.sdf \
  --output /tmp/fs150-test-stripped.sdf \
  --strip-gps true \
  --strip-mag true \
  --strip-baro true >/tmp/fs150-test-strip-render.log
grep -q 'removed 1 x gps include gps0' /tmp/fs150-test-strip-render.log
! grep -q 'magnetometer_plugin' /tmp/fs150-test-stripped.sdf
! grep -q 'barometer_plugin' /tmp/fs150-test-stripped.sdf
! grep -q 'magSubTopic' /tmp/fs150-test-stripped.sdf
! grep -q 'baroSubTopic' /tmp/fs150-test-stripped.sdf

"/opt/ros/${ROS_DISTRO}/lib/gazebo_sim_fs150_sitl/generate_fs150_sitl_params.py" \
  --source "/opt/ros/${ROS_DISTRO}/share/gazebo_sim_fs150_sitl/config/source/fs150-mav_sys_id4.params" \
  --output /tmp/fs150-sitl.params \
  --selection-report /tmp/fs150-sitl.selection.csv \
  --no-runtime-baseline

grep -q 'MPC_THR_HOVER' /tmp/fs150-sitl.params
grep -q 'EKF2_AID_MASK' /tmp/fs150-sitl.params
grep -q $'COM_RC_IN_MODE\t1\t6' /tmp/fs150-sitl.params
grep -q $'COM_RCL_EXCEPT\t4\t6' /tmp/fs150-sitl.params
grep -q 'COM_RC_IN_MODE,1,6,include,sitl_override' /tmp/fs150-sitl.selection.csv
grep -q 'COM_RCL_EXCEPT,4,6,include,sitl_override' /tmp/fs150-sitl.selection.csv
! grep -q $'SYS_HAS_GPS\t0\t6' /tmp/fs150-sitl.params
! grep -q $'SYS_HAS_BARO\t0\t6' /tmp/fs150-sitl.params
! grep -q $'SYS_HAS_MAG\t0\t6' /tmp/fs150-sitl.params
grep -q 'SYS_AUTOSTART,4011,6,exclude' /tmp/fs150-sitl.selection.csv
grep -q 'CAL_ACC0_ID' /tmp/fs150-sitl.selection.csv

echo "Installed FS150 SITL package check passed"
