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

## Estimator Fusion Policy

`config/generated/fs150-sitl.params` is the FS150 SITL startup parameter
overlay.  It is reset into PX4 on launch by default, so estimator behavior is
owned by this package rather than by stale PX4 work-directory state.

The key estimator parameters are:

| Parameter | Value | Meaning in FS150 SITL |
| --- | ---: | --- |
| `EKF2_AID_MASK` | `24` | Enables external vision position and external vision yaw.  This is the main motion-capture aiding selection. |
| `EKF2_HGT_MODE` | `3` | Selects external vision as the primary height source. |
| `EKF2_MAG_TYPE` | `5` | Disables magnetometer fusion.  Yaw should come from motion capture. |
| `EKF2_RNG_AID` | `0` | Prevents PX4 from temporarily switching height fusion to rangefinder at low speed and low altitude. |
| `EKF2_TERR_MASK` | `0` | Disables rangefinder/optical-flow terrain estimation because this indoor workflow does not use HAGL aiding. |
| `MAV_ODOM_LP` | `1` | Keeps MAVLink odometry path behavior aligned with the FS150 motion-capture workflow. |
| `MPC_USE_HTE` | `1` | Enables PX4 hover thrust estimation instead of treating the imported `MPC_THR_HOVER` value as the only hover-thrust source. |

`EKF2_RNG_AID` and `EKF2_TERR_MASK` are deliberately overridden by the FS150
SITL overlay even though the exported real-vehicle FS150 parameter file contains
`EKF2_RNG_AID=1` and `EKF2_TERR_MASK=3`.  In PX4 1.12, range aid can make the
main height fusion use rangefinder when the vehicle is low and slow.  That is
useful for some vehicles, but it is misleading for this indoor FS150 simulation
because altitude behavior should come from motion capture only.

The package does not remove GPS, magnetometer, or barometer plugins from the SDF
by default.  Sensor presence and EKF fusion are separate:

```text
Sensor exists in SITL  !=  EKF fuses that sensor
```

This keeps PX4/Gazebo health behavior stable while making the fusion policy
explicit in the startup parameter overlay.

## Simulation-to-Real Parameter Feedback

Treat this overlay as the record of the simulation fusion hypothesis. Parameters
that are candidates for reverse-sync to the physical FS150 after repeatable
tests include:

- `EKF2_AID_MASK`, `EKF2_HGT_MODE`, `EKF2_MAG_TYPE`
- `EKF2_RNG_AID`, `EKF2_TERR_MASK`
- controller parameters such as `MC_ROLLRATE_*`, `MC_PITCHRATE_*`,
  `MPC_THR_HOVER`, `MPC_USE_HTE`, and `MPC_XY_VEL_D_ACC`

Before copying anything back to a real vehicle, separate the categories:

- Estimator fusion policy can transfer only if the real sensor wiring and
  motion-capture quality match the simulation assumption.
- Controller gains can transfer only after checking actuator, mass, propeller,
  battery, and hover-thrust differences.
- SITL-only convenience parameters such as `COM_RC_IN_MODE=1` and
  `COM_RCL_EXCEPT=4` should not be blindly copied to field aircraft.

After launch, verify the active PX4 parameters with:

```bash
rosrun mavros mavparam -n /uav1/mavros get EKF2_AID_MASK
rosrun mavros mavparam -n /uav1/mavros get EKF2_HGT_MODE
rosrun mavros mavparam -n /uav1/mavros get EKF2_RNG_AID
rosrun mavros mavparam -n /uav1/mavros get EKF2_TERR_MASK
rosrun mavros mavparam -n /uav1/mavros get MPC_USE_HTE
```

The expected values are `24`, `3`, `0`, `0`, and `1`.
