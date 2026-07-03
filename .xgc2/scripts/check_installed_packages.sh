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
test -s "/opt/ros/${ROS_DISTRO}/share/gazebo_sim_fs150_sitl/models/fs150/iris.sdf"

cat >/tmp/fs150-test-base.sdf <<'EOF'
<sdf version="1.6">
  <model name="iris">
    <link name="base_link">
      <inertial>
        <mass>0.260</mass>
        <inertia>
          <ixx>0.001</ixx>
          <ixy>0</ixy>
          <ixz>0</ixz>
          <iyy>0.001</iyy>
          <iyz>0</iyz>
          <izz>0.002</izz>
        </inertia>
      </inertial>
    </link>
    <include><uri>model://gps</uri><name>gps0</name></include>
    <joint name="gps0_joint" type="fixed">
      <child>gps0::link</child>
      <parent>base_link</parent>
    </joint>
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
grep -q 'updated 1 x gps include gps0' /tmp/fs150-test-render.log
grep -q 'updated 1 x gps joint gps0_joint' /tmp/fs150-test-render.log
! grep -q 'gps0' /tmp/fs150-test-indoor.sdf
grep -q '<mass>0.275</mass>' /tmp/fs150-test-indoor.sdf
grep -q 'magnetometer_plugin' /tmp/fs150-test-indoor.sdf
grep -q 'barometer_plugin' /tmp/fs150-test-indoor.sdf
grep -q 'magSubTopic' /tmp/fs150-test-indoor.sdf
grep -q 'baroSubTopic' /tmp/fs150-test-indoor.sdf

"/opt/ros/${ROS_DISTRO}/lib/gazebo_sim_fs150_sitl/render_fs150_indoor_sdf.py" \
  --base-sdf /tmp/fs150-test-base.sdf \
  --output /tmp/fs150-test-stripped.sdf \
  --strip-mag true \
  --strip-baro true >/tmp/fs150-test-strip-render.log
grep -q 'updated 1 x gps include gps0' /tmp/fs150-test-strip-render.log
! grep -q 'gps0' /tmp/fs150-test-stripped.sdf
! grep -q 'magnetometer_plugin' /tmp/fs150-test-stripped.sdf
! grep -q 'barometer_plugin' /tmp/fs150-test-stripped.sdf
! grep -q 'magSubTopic' /tmp/fs150-test-stripped.sdf
! grep -q 'baroSubTopic' /tmp/fs150-test-stripped.sdf

"/opt/ros/${ROS_DISTRO}/lib/gazebo_sim_fs150_sitl/generate_fs150_sitl_params.py" \
  --source "/opt/ros/${ROS_DISTRO}/share/gazebo_sim_fs150_sitl/firmware/fs150-mav_sys_id4.params" \
  --output /tmp/fs150-sitl.params \
  --selection-report /tmp/fs150-sitl.selection.csv \
  --no-runtime-baseline

grep -q 'MPC_THR_HOVER' /tmp/fs150-sitl.params
grep -q 'EKF2_AID_MASK' /tmp/fs150-sitl.params
grep -q $'COM_ARM_WO_GPS\t1\t6' /tmp/fs150-sitl.params
grep -q $'EKF2_GPS_CHECK\t0\t6' /tmp/fs150-sitl.params
grep -q $'NAV_DLL_ACT\t2\t6' /tmp/fs150-sitl.params
grep -q $'NAV_RCL_ACT\t2\t6' /tmp/fs150-sitl.params
grep -q $'COM_OBL_ACT\t0\t6' /tmp/fs150-sitl.params
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
