# FS150 IMU over MAVROS

Practical high-rate raw IMU on PX4 1.12 FS150 / matching SITL:

```text
IMU_GYRO_RATEMAX = 800
IMU_INTEG_RATE   = 800
stream           = HIGHRES_IMU(105) at 250 Hz
topic            = /mavros/imu/data_raw
```

Prefer 105 over `SCALED_IMU(26)`. Remote UDP `14560` may block 105; onboard
`127.0.0.1:14561` does not. Measurements and why 300 Hz fails:
`memory/field/fs150/imu-highres-mavlink.md` (`xgc2-dev-memory`).
