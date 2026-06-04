# gazebo_sim_fs150_sitl

FS150 SITL is a thin wrapper over the PX4 1.12 iris Gazebo simulation. It keeps
the iris airframe, mixer, core multirotor dynamics and simulated IMU owned by
the base simulator, then overlays only the real FS150 parameters that are useful
for matching control, power policy, safety policy and mocap/vision estimator
behavior.

Start the default vehicle-4 simulation:

```bash
roslaunch gazebo_sim_fs150_sitl fs150.launch
```

For indoor mocap simulation, render a local SDF from the currently installed PX4
1.12 iris model, stripping the unused Gazebo GPS, magnetometer and barometer
simulation:

```bash
rosrun gazebo_sim_fs150_sitl render_fs150_indoor_sdf.py
roslaunch gazebo_sim_fs150_sitl fs150.launch \
  sdf:=$HOME/.xgc2/fs150_sitl/iris_indoor.sdf
```

The renderer reads the installed `gazebo_sim_px4_1_12` iris SDF and falls back
to `/opt/ros/$ROS_DISTRO/share/...` if a development source package shadows the
installed runtime package. The FS150 package does not fork or modify the PX4
1.12 SITL package.

For multiple vehicles, change both the PX4 instance and the MAVROS URL:

```bash
roslaunch gazebo_sim_fs150_sitl fs150.launch \
  ID:=4 \
  model_name:=fs150_4 \
  fcu_url:=udp://:14544@localhost:14561
```

Regenerate the SITL overlay after updating the real FS150 export:

```bash
rosrun gazebo_sim_fs150_sitl generate_fs150_sitl_params.py \
  --source "$(rospack find gazebo_sim_fs150_sitl)/config/source/fs150-mav_sys_id4.params" \
  --output "$(rospack find gazebo_sim_fs150_sitl)/config/generated/fs150-sitl.params" \
  --selection-report "$(rospack find gazebo_sim_fs150_sitl)/config/generated/fs150-sitl.selection.csv"
```

The generator intentionally rejects airframe identity, sensor calibration, RC,
PWM, serial hardware, GPS hardware and MAVLink port/mode parameters.  PX4 SITL
injects `MAV_SYS_ID` from the instance ID, so the default `ID:=3` maps to
vehicle id 4 without hardcoding `MAV_SYS_ID` in the parameter file.
