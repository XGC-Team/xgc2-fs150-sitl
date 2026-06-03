# gazebo_sim_fs150_sitl

FS150 SITL is a thin wrapper over the PX4 1.12 iris Gazebo simulation.  It keeps
the iris airframe, mixer, Gazebo SDF and simulated sensor calibration owned by
the base simulator, then overlays only the real FS150 parameters that are useful
for matching control, power policy, safety policy and mocap/vision estimator
behavior.

Start the default vehicle-4 simulation:

```bash
roslaunch gazebo_sim_fs150_sitl fs150.launch
```

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
