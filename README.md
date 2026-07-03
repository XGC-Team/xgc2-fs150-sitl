# gazebo_sim_fs150_sitl

FS150 SITL is a thin wrapper over the PX4 1.12 iris Gazebo simulation. It keeps
the iris airframe, mixer, and simulated IMU startup path owned by the base
simulator, then overlays the real FS150 parameters plus FS150 total mass,
equivalent compact-frame inertia, and hover-calibrated Gazebo motor constants
for matching control, power policy, safety policy and mocap/vision estimator
behavior.

Start the default vehicle-4 simulation:

```bash
roslaunch gazebo_sim_fs150_sitl fs150.launch
```

For indoor mocap simulation, render a local SDF with the same FS150 dynamics.
The default rendered model removes the `gps0` include/joint entirely and keeps
the removed GPS mass inside `base_link`, so there is no Gazebo GPS sensor,
plugin, link, or black GPS marker:

```bash
rosrun gazebo_sim_fs150_sitl render_fs150_indoor_sdf.py
roslaunch gazebo_sim_fs150_sitl fs150.launch \
  sdf:=$HOME/.xgc2/fs150_sitl/iris_indoor.sdf
```

The default launch already uses `models/fs150/iris.sdf` from this package. That
SDF keeps the iris PX4 airframe, mixer assumptions, rotor geometry, collision
geometry, and visible geometry unchanged. The default model has no `gps0`
include/joint, so Gazebo does not publish GPS and no GPS visual marker is
shown. The removed GPS mass is folded into `base_link`. The SDF changes only
the FS150 equivalent dynamics terms:

| Quantity | FS150 SITL value |
| --- | ---: |
| Total Gazebo mass | `0.310 kg` |
| `base_link` mass | `0.275 kg` |
| Base inertia | Iris base inertia scaled by `0.275 / 1.5 * 0.35` |
| Base inertia values | `ixx=iyy=0.00186885417`, `izz=0.00354360417` |
| Body collision size | Iris default `0.47 x 0.47 x 0.11 m` |
| Body visual mesh | Iris default `iris.stl` |
| Body visual pose | `0 0 0 0 0 0` |
| Body visual scale | Iris default `1 1 1` |
| Rotor centers | Iris default rotor poses |
| Rotor z offset | Iris default `0.023 m` |
| Propeller radius | Iris default `0.128 m` |
| Rotor collision cylinder | Iris default `radius 0.128 m`, `length 0.005 m` |
| Propeller visual scale | Iris default `1 1 1` |
| `gps0` model | Removed |
| `motorConstant` hover-corrected value | `5.33969944334e-06` |
| `momentConstant` | `0.06` |
| `timeConstantUp/Down` | `0.006 / 0.012 s` |
| `rotorDragCoefficient` | `2e-05` |
| `rollingMomentCoefficient` | `1e-07` |

The renderer applies the same FS150 mass, equivalent inertia, Iris geometry,
motor constants, motor response and rotor drag when generating a local indoor
variant. GPS is not configurable in this renderer: FS150 is treated as a
no-GPS vehicle, so any `gps0` include/joint in the source SDF is always removed
and the `0.015 kg` GPS mass is carried by `base_link`. If `--body-mass` is
overridden, the script keeps the same 0.35 compact frame inertia factor while
scaling by the requested mass. The FS150 package does not modify the PX4 1.12
SITL package.

The `motorConstant` started from total-mass scaling of the previous
hover-calibrated heavy model and was then corrected by FS150 hover testing.
For future hover tests, correct it with:

```text
motorConstant_next = motorConstant_current * (observed_hover_thrust / 0.30)^2
```

where `observed_hover_thrust` is the stable PX4 HTE or ROS hover-thrust
estimate. The target is `0.30 +/- 0.03`.

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
  --source "$(rospack find gazebo_sim_fs150_sitl)/firmware/fs150-mav_sys_id4.params" \
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

The indoor no-GPS and failsafe parameters are:

| Parameter | Value | Meaning in FS150 SITL |
| --- | ---: | --- |
| `COM_ARM_WO_GPS` | `1` | Allows arming when no GPS is present. |
| `EKF2_GPS_CHECK` | `0` | Disables GPS quality checks for the no-GPS indoor model. |
| `COM_POSCTL_NAVL` | `0` | On position-control navigation loss, fall back to Altitude if height is available, otherwise Manual. |
| `COM_TAKEOFF_ACT` | `0` | Matches the real FS150 export: on takeoff failure, choose Hold instead of trying to resume Mission. |
| `NAV_DLL_ACT` | `2` | Matches the real FS150 export: if the GCS/data link is lost, choose Return. |
| `NAV_RCL_ACT` | `2` | Matches the real FS150 export: if RC/manual control is lost, choose Return. |
| `COM_OBL_ACT` | `0` | Matches the real FS150 export: if Offboard setpoints stop, choose Land mode. |

`EKF2_RNG_AID` and `EKF2_TERR_MASK` are deliberately overridden by the FS150
SITL overlay even though the exported real-vehicle FS150 parameter file contains
`EKF2_RNG_AID=1` and `EKF2_TERR_MASK=3`.  In PX4 1.12, range aid can make the
main height fusion use rangefinder when the vehicle is low and slow.  That is
useful for some vehicles, but it is misleading for this indoor FS150 simulation
because altitude behavior should come from motion capture only.

The package removes the Gazebo GPS model entirely: no `gps0` include, no
`gps0` joint, no GPS link, and no GPS plugin. Magnetometer and barometer
plugins are still present by default, while EKF fusion is selected explicitly by
parameters. Sensor presence and EKF fusion are separate:

```text
Sensor exists in SITL  !=  EKF fuses that sensor
```

This makes the sensor model closer to the real FS150 behavior: no GPS aiding is
available in Gazebo.  Failsafe parameters that already exist in the real FS150
export, including `NAV_DLL_ACT` and `NAV_RCL_ACT`, are mirrored instead of
being changed silently. PX4 1.12 parameters alone cannot guarantee that every
AUTO submode is rejected; if `AUTO.LAND` is still accepted, that is a known
limitation of the pure parameter approach. A hard ban would need a MAVROS-side
mode guard or a PX4 commander/navigator patch.

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
  battery, and hover-thrust differences. The packaged FS150 SDF currently
  aligns total mass, first-pass inertia, Gazebo rotor geometry, propeller
  radius and motor thrust constant while keeping PX4 mixer and airframe
  identity iris-owned.
- SITL-only convenience parameters such as `COM_RC_IN_MODE=1` and
  `COM_RCL_EXCEPT=4` should not be blindly copied to field aircraft.

After launch, verify the active PX4 parameters with:

```bash
rosrun mavros mavparam -n /uav1/mavros get EKF2_AID_MASK
rosrun mavros mavparam -n /uav1/mavros get EKF2_HGT_MODE
rosrun mavros mavparam -n /uav1/mavros get EKF2_RNG_AID
rosrun mavros mavparam -n /uav1/mavros get EKF2_TERR_MASK
rosrun mavros mavparam -n /uav1/mavros get MPC_USE_HTE
rosrun mavros mavparam -n /uav1/mavros get COM_ARM_WO_GPS
rosrun mavros mavparam -n /uav1/mavros get EKF2_GPS_CHECK
rosrun mavros mavparam -n /uav1/mavros get NAV_DLL_ACT
rosrun mavros mavparam -n /uav1/mavros get NAV_RCL_ACT
```

The expected values are `24`, `3`, `0`, `0`, `1`, `1`, `0`, `2`, and `2`.
