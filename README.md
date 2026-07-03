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

For indoor mocap simulation, render a local SDF with the same FS150 dynamics,
optionally stripping the unused Gazebo GPS, magnetometer and barometer
simulation:

```bash
rosrun gazebo_sim_fs150_sitl render_fs150_indoor_sdf.py
roslaunch gazebo_sim_fs150_sitl fs150.launch \
  sdf:=$HOME/.xgc2/fs150_sitl/iris_indoor.sdf
```

The default launch already uses `models/fs150/iris.sdf` from this package. That
SDF keeps the iris PX4 airframe, mixer assumptions, rotor geometry, collision
geometry, visible geometry, and GPS pose unchanged. It changes only the FS150
equivalent dynamics terms:

| Quantity | FS150 SITL value |
| --- | ---: |
| Total Gazebo mass, including `gps0` | `0.310 kg` |
| `base_link` mass | `0.260 kg` |
| Base inertia | Iris base inertia scaled by `0.260 / 1.5 * 0.35` |
| Base inertia values | `ixx=iyy=0.00176691667`, `izz=0.00335031667` |
| Body collision size | Iris default `0.47 x 0.47 x 0.11 m` |
| Body visual mesh | Iris default `iris.stl` |
| Body visual pose | `0 0 0 0 0 0` |
| Body visual scale | Iris default `1 1 1` |
| Rotor centers | Iris default rotor poses |
| Rotor z offset | Iris default `0.023 m` |
| Propeller radius | Iris default `0.128 m` |
| Rotor collision cylinder | Iris default `radius 0.128 m`, `length 0.005 m` |
| Propeller visual scale | Iris default `1 1 1` |
| `gps0` pose | Iris default `0.1 0 0 0 0 0` |
| `motorConstant` hover-corrected value | `5.33969944334e-06` |
| `momentConstant` | `0.06` |
| `timeConstantUp/Down` | `0.006 / 0.012 s` |
| `rotorDragCoefficient` | `2e-05` |
| `rollingMomentCoefficient` | `1e-07` |

The renderer applies the same FS150 mass, equivalent inertia, Iris geometry,
motor constants, motor response and rotor drag when generating a local indoor
variant. If `--body-mass` is overridden, the script keeps the same 0.35 compact
frame inertia factor while scaling by the requested mass. The FS150 package does
not modify the PX4 1.12 SITL package.

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
```

The expected values are `24`, `3`, `0`, `0`, and `1`.
