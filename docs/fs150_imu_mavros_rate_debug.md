# FS150 IMU, MAVLink, and MAVROS Rate Debug Notes

This note records the real FS150 IMU telemetry investigation done on the PX4
1.12.3.dev based aircraft.  It is written for the physical aircraft first, then
can be used as the reference when aligning SITL.

## Result Summary

The useful raw-IMU MAVROS path on FS150 is:

```text
BMI088 accel/gyro
  -> PX4 sensor_accel / sensor_gyro
  -> PX4 vehicle_imu
  -> MAVLink HIGHRES_IMU(105)
  -> mavlink-router TCP 5760
  -> MAVROS /mavros/imu/data_raw
```

The current practical recommendation is:

```text
IMU_GYRO_RATEMAX = 800
IMU_INTEG_RATE   = 800
MAVLink message  = HIGHRES_IMU(105)
MAVROS rate      = 250 Hz
```

With this setup, the measured result was:

| Request | Direct MAVLink result | MAVROS `/mavros/imu/data_raw` result | Notes |
| --- | ---: | ---: | --- |
| `HIGHRES_IMU(105) = 200 Hz` | about `199 Hz` | about `199 Hz` | Stable and clean. |
| `HIGHRES_IMU(105) = 250 Hz` | about `247 Hz` | about `247 Hz` | Current best high-rate choice. |
| `HIGHRES_IMU(105) = 300 Hz` | about `221-222 Hz` | about `222 Hz` | No duplicate payloads, but not rate-accurate. |
| `HIGHRES_IMU(105) = 600 Hz` | about `333 Hz` | not recommended | Starts MAVLink bandwidth scaling and still does not reach request rate. |

The 300 Hz and 600 Hz tests did not produce repeated timestamp or repeated
payload samples.  They simply did not deliver the requested number of messages.

## Why `HIGHRES_IMU(105)` Is Used

Initially the aircraft's `mavlink-router` blocked message 105:

```ini
BlockMsgIdIn = 105, 106, 331
BlockMsgIdOut = 105, 106, 331
```

That was reasonable for normal remote MAVROS use because `HIGHRES_IMU` can take
bandwidth.  For raw-IMU rate work it must be unblocked:

```ini
BlockMsgIdIn = 106, 331
BlockMsgIdOut = 106, 331
```

`106` is `OPTICAL_FLOW_RAD`; `331` is `ODOMETRY`.  Those were left blocked.

Use `HIGHRES_IMU(105)` instead of `SCALED_IMU(26)` for high-rate raw IMU:

| Message | MAVROS topic | PX4 source | Timestamp | Payload |
| --- | --- | --- | --- | --- |
| `SCALED_IMU(26)` | `/mavros/imu/data_raw` | `vehicle_imu` | `time_boot_ms` in milliseconds | integer scaled values |
| `HIGHRES_IMU(105)` | `/mavros/imu/data_raw` | `vehicle_imu` | `time_usec` / sample timestamp | floating point values |
| `ATTITUDE_QUATERNION(31)` | `/mavros/imu/data` | attitude estimate | estimator/fused output | not raw IMU |

`SCALED_IMU(26)` can look repeated at high rates because it uses millisecond
timestamps and integer quantized payload fields.  `HIGHRES_IMU(105)` avoided
that issue during testing.

## PX4 Source Timing Chain

Important PX4 1.12 source locations:

```text
src/drivers/imu/bosch/bmi088/BMI088_Gyroscope.cpp
src/drivers/imu/bosch/bmi088/BMI088_Gyroscope.hpp
src/lib/drivers/gyroscope/PX4Gyroscope.hpp
src/lib/drivers/accelerometer/PX4Accelerometer.hpp
src/modules/sensors/vehicle_imu/VehicleIMU.cpp
src/modules/mavlink/streams/HIGHRES_IMU.hpp
src/modules/mavlink/streams/SCALED_IMU.hpp
src/modules/mavlink/mavlink_receiver.cpp
src/modules/mavlink/mavlink_stream.cpp
```

### 1. BMI088 Driver Rate

The FS150 primary IMU is BMI088:

```text
gyro device type: 0x66
accel device type: 0x6a
```

`IMU_GYRO_RATEMAX` is read by `PX4Gyroscope` and used by the BMI088 driver
through `get_max_rate_hz()`.  It is a requested maximum, not a guarantee that
the published `sensor_gyro` topic will exactly equal the parameter.

Measured with `IMU_GYRO_RATEMAX=800`:

```text
sensor_gyro       about 666 Hz
sensor_gyro_fifo  about 666 Hz
sensor_accel      about 796 Hz
sensor_accel_fifo about 796 Hz
gyro raw FIFO     about 1999 Hz
accel raw FIFO    about 1591 Hz
```

So the BMI088 itself is not a 100 Hz or 250 Hz bottleneck.

### 2. `vehicle_imu` Integration Rate

`IMU_INTEG_RATE` controls the target integration rate for `vehicle_imu`.
`VehicleIMU.cpp` integrates raw accel/gyro samples into:

```text
delta_angle
delta_velocity
delta_angle_dt
delta_velocity_dt
```

The generated `vehicle_imu` is what EKF and the MAVLink IMU streams consume.
It is not a direct one-message-per-raw-sensor-sample stream.

The implementation lets gyro drive the integration and makes accel follow the
gyro interval.  The effective integration interval is quantized to an integer
number of gyro samples:

```cpp
gyro_integral_samples = round(IMU_INTEG_INTERVAL / gyro_interval)
integration_interval  = gyro_integral_samples * gyro_interval
```

Measured examples:

| Parameters | Actual `sensor_gyro` | Actual `vehicle_imu` | Explanation |
| --- | ---: | ---: | --- |
| `IMU_GYRO_RATEMAX=800`, `IMU_INTEG_RATE=200` | about `666 Hz` | about `194-196 Hz` | Close to 200 Hz, but with scheduling jitter. |
| `IMU_GYRO_RATEMAX=800`, `IMU_INTEG_RATE=400` | about `666 Hz` | about `333 Hz` | 400 Hz target quantizes to 2 gyro samples: `666 / 2`. |
| `IMU_GYRO_RATEMAX=800`, `IMU_INTEG_RATE=800` | about `666 Hz` | about `666 Hz` | Target is faster than gyro topic, so it publishes each gyro update. |

Both parameters are marked reboot-required in PX4 metadata.  Change them,
reboot the flight controller, then measure the actual topic rates.

### 3. MAVLink Stream Scheduling

`HIGHRES_IMU.hpp` subscribes to `vehicle_imu`, not to the BMI088 driver topic.
It sends a MAVLink message only when the `vehicle_imu` subscription updates.
Skipped `vehicle_imu` samples are not queued and backfilled by the MAVLink
stream.

`mavlink_stream.cpp` schedules streams by message interval and rate multiplier.
This means the effective outgoing rate depends on:

- requested message interval,
- MAVLink main loop timing,
- whether `vehicle_imu` has a new sample at that moment,
- link bandwidth scaling through `rate_mult`,
- other streams on the same MAVLink instance.

This is why `vehicle_imu=666 Hz` did not automatically make
`HIGHRES_IMU=300 Hz` reliable.  Direct measurements showed:

```text
250 Hz request -> about 247 Hz actual
300 Hz request -> about 221-222 Hz actual
600 Hz request -> about 333 Hz actual
```

At 300 Hz, `mavlink status` showed:

```text
txerr: 0
tx rate mult: 1.000
HIGHRES_IMU configured/current: about 300 Hz
actual receive rate: about 221 Hz
```

So 300 Hz was not mainly a serial bandwidth problem.  It was MAVLink stream
timing/capture behavior.

At 600 Hz, `mavlink status` showed:

```text
tx rate mult: 0.913
HIGHRES_IMU configured: about 600 Hz
HIGHRES_IMU current: about 548 Hz
actual receive rate: about 333 Hz
```

So 600 Hz starts to hit bandwidth scaling and still loses samples through the
stream scheduling path.  It is not a clean setting.

## QGroundControl Parameter Editing Notes

QGC may show a parameter maximum that is higher than the combo-box choices.
For `IMU_INTEG_RATE`, PX4 metadata allows:

```text
min: 100
max: 1000
listed values: 100, 200, 250, 400
reboot_required: true
```

The normal QGC combo box only shows the listed values.  To set `800`, enable
advanced/manual entry in the parameter editor and type the value manually.
This is valid because `800` is inside the metadata min/max range even though it
is not in the combo-box list.

After changing `IMU_INTEG_RATE` or `IMU_GYRO_RATEMAX`, reboot the flight
controller and verify with PX4 shell:

```text
param show IMU_INTEG_RATE
param show IMU_GYRO_RATEMAX
uorb top -1 vehicle_imu
uorb top -1 sensor_gyro
listener vehicle_imu_status 1
```

## Useful PX4 Shell Commands

The aircraft exposes MAVLink through `mavlink-router`:

```text
TCP server: 192.168.51.14:5760
UART to FCU: /dev/ttyS7 @ 921600 in mavlink-router
PX4 companion instance: /dev/ttyS0 @ 921600
```

Open PX4 MAVLink shell from the host:

```bash
python3 external/flight/px4_1_12/PX4-Autopilot/Tools/mavlink_shell.py \
  tcp:192.168.51.14:5760
```

Useful commands inside the shell:

```text
param show IMU_INTEG_RATE
param show IMU_GYRO_RATEMAX
listener vehicle_imu_status 1
uorb top -1 vehicle_imu
uorb top -1 sensor_gyro
uorb top -1 sensor_accel
uorb top -1 sensor_combined
mavlink status
mavlink status streams
```

Interpretation:

- `listener vehicle_imu_status 1` shows selected IMU device IDs, measured raw
  rates, error counts, clipping and vibration metrics.
- `uorb top -1 vehicle_imu` shows the actual internal `vehicle_imu` publish
  rate after integration-rate quantization.
- `mavlink status` shows link budget, `txerr`, `tx rate mult`, and actual
  transmit rate.
- `mavlink status streams` shows the stream configured rate and current rate
  after PX4 bandwidth scaling.  Actual received rate can still be lower if the
  stream misses `vehicle_imu` updates.

## Useful MAVROS Commands

Start temporary MAVROS from the host:

```bash
export ROS_MASTER_URI=http://127.0.0.1:11312
roscore -p 11312
```

In another terminal:

```bash
export ROS_MASTER_URI=http://127.0.0.1:11312
roslaunch mavros px4.launch \
  fcu_url:=tcp://192.168.51.14:5760 \
  tgt_system:=4 \
  tgt_component:=0
```

Request high-rate raw IMU:

```bash
rosservice call /mavros/set_message_interval "message_id: 105
message_rate: 250.0"
```

Measure the ROS topic:

```bash
rostopic hz /mavros/imu/data_raw
```

Stop/reset the requested stream when done and verify that 105 stops:

```bash
rosservice call /mavros/set_message_interval "message_id: 105
message_rate: 0.0"
```

For direct MAVLink, the lower-level PX4 command semantics are different:

```text
MAV_CMD_SET_MESSAGE_INTERVAL param2 > 0 : interval in microseconds
MAV_CMD_SET_MESSAGE_INTERVAL param2 = 0 : restore default rate
MAV_CMD_SET_MESSAGE_INTERVAL param2 < 0 : stop stream
```

So a direct pymavlink stop should send `param2=-1`.

## Direct pymavlink Probe

This is useful to separate PX4/router behavior from MAVROS conversion:

```python
#!/usr/bin/env python3
import time
from pymavlink import mavutil

HOST = "tcp:192.168.51.14:5760"
TARGET_SYSTEM = 4
TARGET_COMPONENT = 0
HIGHRES_IMU = 105

def heartbeat(master):
    master.mav.heartbeat_send(
        mavutil.mavlink.MAV_TYPE_GCS,
        mavutil.mavlink.MAV_AUTOPILOT_INVALID,
        0, 0, 0)

def set_interval(master, msg_id, hz):
    if hz == "stop":
        interval_us = -1
    else:
        interval_us = int(round(1_000_000.0 / hz))

    for _ in range(3):
        heartbeat(master)
        master.mav.command_long_send(
            TARGET_SYSTEM,
            TARGET_COMPONENT,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
            0,
            msg_id,
            interval_us,
            0, 0, 0, 0, 0)
        time.sleep(0.15)

master = mavutil.mavlink_connection(
    HOST,
    source_system=255,
    source_component=190,
    autoreconnect=False,
    robust_parsing=True)

deadline = time.time() + 8
while time.time() < deadline:
    msg = master.recv_match(type="HEARTBEAT", blocking=True, timeout=0.5)
    if msg and msg.get_srcSystem() == TARGET_SYSTEM:
        break
else:
    raise RuntimeError("PX4 heartbeat not found")

try:
    set_interval(master, HIGHRES_IMU, 250)
    time.sleep(1.0)

    t0 = time.time()
    last_heartbeat = 0.0
    times = []
    payloads = []

    while time.time() - t0 < 10.0:
        now = time.time()
        if now - last_heartbeat > 1.0:
            heartbeat(master)
            last_heartbeat = now

        msg = master.recv_match(blocking=True, timeout=0.4)
        if not msg or msg.get_type() != "HIGHRES_IMU":
            continue

        times.append(int(msg.time_usec))
        payloads.append((
            round(msg.xacc, 7), round(msg.yacc, 7), round(msg.zacc, 7),
            round(msg.xgyro, 7), round(msg.ygyro, 7), round(msg.zgyro, 7)))

    dt = time.time() - t0
    print(f"rate={len(times) / dt:.2f} Hz samples={len(times)}")
    print("consecutive timestamp duplicates:",
          sum(1 for a, b in zip(times, times[1:]) if a == b))
    print("consecutive payload duplicates:",
          sum(1 for a, b in zip(payloads, payloads[1:]) if a == b))

finally:
    set_interval(master, HIGHRES_IMU, "stop")
```

When multiple MAVLink clients are connected, do not rely on the first heartbeat
to choose the target.  Wait for a heartbeat from system id `4`, or set the
target system/component explicitly as shown above.

## Recommended Validation Checklist

After changing IMU rates:

```text
1. Reboot the flight controller.
2. Confirm parameters:
   param show IMU_GYRO_RATEMAX
   param show IMU_INTEG_RATE
3. Confirm internal source:
   listener vehicle_imu_status 1
   uorb top -1 sensor_gyro
   uorb top -1 vehicle_imu
4. Request HIGHRES_IMU(105) through MAVROS or direct pymavlink.
5. Measure /mavros/imu/data_raw with rostopic hz.
6. Check mavlink status:
   - txerr should stay 0
   - tx rate mult should stay close to 1 for clean settings
   - instance #1 tx should stay below tx rate max
7. Stop the requested stream after the test.
8. Verify no HIGHRES_IMU continues to be transmitted when not requested.
```

For the current FS150 aircraft, `250 Hz` is the highest tested setting that is
both close to requested rate and not obviously stressing the MAVLink link.
`300 Hz` and above are useful diagnostic tests, but not good default operating
points on the PX4 1.12 MAVLink stream path.
