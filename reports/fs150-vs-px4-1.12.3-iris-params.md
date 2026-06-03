# FS150 exported parameters vs PX4 v1.12.3 Iris SITL defaults

## 中文结论

这份对比不是简单比较“默认值是否相等”，而是在回答一个更具体的问题：

> 从 FS150 实物飞控导出的 PX4 v1.12.3 参数，哪些代表真实飞机的行为特征，适合带入 SITL；哪些只是硬件板卡、传感器、串口、UAVCAN、遥控器等实物环境痕迹，不应该直接灌进仿真。

本次比较基线是已安装的 PX4 v1.12.3 SITL runtime：

```text
/opt/ros/noetic/share/px4_sitl_runtime_1_12/runtime
```

`PX4_SIM_MODEL=iris` 在这个 runtime 中实际匹配的是：

```text
etc/init.d-posix/airframes/10016_iris
```

因此 v1.12.3 的 `iris` 默认仿真不是 `10015_gazebo-classic_iris`，后者属于更新命名体系。这个差异非常关键：如果后续做 `gazebo_sim_fs150`，不要直接照搬 v1.14 的 airframe 名称。

## 总体差异规模

| 项目 | 数量 | 含义 |
| --- | ---: | --- |
| FS150 导出参数 | 801 | 实物飞控导出的唯一参数名数量 |
| SITL v1.12.3 有效参数 | 1462 | metadata 默认值加上 `rcS`、`rc.mc_defaults`、`10016_iris` 的确定性覆盖 |
| 完全一致 | 631 | 这些参数不需要关心，导入与否对默认 SITL 没有区别 |
| 不一致 | 122 | 重点分析对象 |
| FS150 有但 SITL metadata 没有 | 48 | 多数是板卡、串口、UAVCAN、旧/定制参数；不应无脑导入 |
| SITL 有但 FS150 没导出 | 709 | SITL/PX4 默认参数全集里存在，但实物导出文件没有覆盖 |

## 应该如何读这个报告

后面的全量表里：

- `FS150`：实物飞控导出的值。
- `SITL iris default`：PX4 v1.12.3 `iris` 首次启动后的有效默认值。
- `Delta`：`FS150 - SITL`，只对数值参数有意义。
- `same`：两边一致。
- `different`：两边都存在，但值不同。
- `missing_in_sim_metadata`：FS150 导出了，但当前 v1.12.3 SITL 参数表没有这个参数名。
- `not_exported_by_fs150`：SITL 有，但 FS150 导出文件没有。

真正需要用于封装的主要是 `different` 里面的控制、估计、任务、安全策略、电源模型参数；`missing_in_sim_metadata` 里面大多不能直接用于 SITL。

## 参数类别含义与建议

| 类别 | 差异数 | 结论 | 是否建议导入 SITL |
| --- | ---: | --- | --- |
| Sensor calibration | 38 | 真实 IMU、陀螺仪、磁力计的 ID、offset、scale、rotation。SITL 使用模拟传感器 ID 和理想标定。 | 默认不导入 |
| RC/operator input | 23 | 遥控器通道、行程、反向、开关映射。只影响手动遥控/模式开关。 | 只在仿真遥控器工作流中导入 |
| Commander/failsafe | 10 | 失联、低电、解锁、降落后自动上锁等策略。会明显影响仿真安全行为。 | 谨慎导入 |
| Battery/power | 8 | 三电芯、电压分压、电压阈值、电流换算。适合做 FS150 电源特性模拟。 | 建议拆成电源 profile |
| MAVLink/system identity | 6 | 系统 ID、MAVLink 实例、转发、速率。影响 QGC、MAVROS、多机识别。 | 按实例导入，不要写死 |
| Multicopter attitude/rate | 6 | 姿态角速度控制器增益。体现实机控制调参。 | 建议导入到 FS150 控制 profile |
| Multicopter position | 3 | 悬停油门、水平速度控制等。会影响飞行手感和轨迹响应。 | 建议导入到 FS150 控制 profile |
| Estimator | 4 | EKF 融合源、高度源、磁航向策略、GPS 精度要求。必须和仿真传感器/VRPN/vision 数据源一致。 | 条件导入 |
| IMU runtime | 3 | IMU 积分频率、滤波截止频率。和仿真 IMU 频率、控制环有关。 | 谨慎导入 |
| Logging | 3 | 日志策略。对飞行行为影响小，但影响磁盘和调试。 | 通常不导入 |
| Actuator output | 3 | PWM 输出范围和输出掩码。仿真里通常由 mixer/SDF/插件决定。 | 谨慎导入 |
| Return/landing | 3 | RTL 高度、降落延时、返航下降高度。会影响任务行为。 | 可导入 |
| Safety circuit breaker | 1 | `CBRK_SUPPLY_CHK`。SITL 默认绕过供电检查，实机没有绕过。 | 不建议直接导入 |
| System/autostart | 1 | `SYS_AUTOSTART` 实物是 `4011`，SITL iris 是 `10016`。 | 不要直接导入 |

## 关键差异解释

| 参数 | FS150 | SITL iris | 含义 | 建议 |
| --- | ---: | ---: | --- | --- |
| `SYS_AUTOSTART` | 4011 | 10016 | 实物 airframe 和 SITL iris airframe 完全不同。SITL 通过 `PX4_SIM_MODEL=iris` 找到 `10016_iris`。 | 不要把 `4011` 直接导入，除非你为 FS150 新增了对应 airframe 启动脚本 |
| `MAV_SYS_ID` | 4 | 1 | 实物飞控是 4 号机；默认 SITL 第 0 个实例是 1 号机。 | 多机仿真应通过 launch `ID` 或 profile 设置，不要全局写死 |
| `MPC_THR_HOVER` | 0.36 | 0.5 | 实机悬停油门明显低于默认 iris。 | 建议导入，否则仿真控制器的油门估计不像 FS150 |
| `MC_ROLLRATE_P/I/D` | 0.07 / 0.07 / 0.001 | 0.15 / 0.2 / 0.003 | 实机横滚角速度环比默认 iris 保守很多。 | 建议导入控制 profile |
| `MC_PITCHRATE_P/I/D` | 0.07 / 0.05 / 0.001 | 0.15 / 0.2 / 0.003 | 实机俯仰角速度环比默认 iris 保守很多。 | 建议导入控制 profile |
| `MPC_XY_VEL_D_ACC` | 0.25 | 0.2 | 水平速度控制 D 项不同。 | 可导入 |
| `MPC_MANTHR_MIN` | 0.04 | 0.08 | 手动最低油门不同。 | 如果需要手动飞行仿真，可导入 |
| `EKF2_AID_MASK` | 24 | 1 | 实机估计器融合源和默认 SITL 不同，通常和视觉/外部定位工作流相关。 | 只有当仿真提供对应 vision/VRPN 数据时才导入 |
| `EKF2_HGT_MODE` | 3 | 0 | 高度源选择不同。 | 必须和仿真传感器源一致，否则 EKF 可能异常 |
| `EKF2_MAG_TYPE` | 5 | 0 | 磁航向处理策略不同。 | 如果仿真没有真实磁干扰，不建议盲目照搬 |
| `EKF2_REQ_GPS_H` | 10 | 0.5 | 实机对 GPS 水平精度要求更严格。 | 如果使用 GPS SITL，可考虑导入；如果用外部视觉，需结合 `EKF2_AID_MASK` |
| `BAT_N_CELLS` | 3 | 4 | FS150 是 3S 电池；SITL 默认 4S。 | 建议导入电源 profile |
| `BAT_V_CHARGED` | 4.35 | 4.05 | 单节满电电压不同。 | 建议导入电源 profile |
| `BAT_V_EMPTY` | 3.60 | 3.50 | 单节空电电压不同。 | 建议导入电源 profile |
| `BAT_V_DIV` | 19.269 | -1 | 实物电压分压系数，SITL 默认无硬件分压。 | 不一定需要，除非仿真电池模型读取该参数 |
| `CBRK_SUPPLY_CHK` | 0 | 894281 | SITL 默认绕过供电检查；实机未绕过。 | 不建议导入，否则 SITL 可能因供电检查行为变化增加干扰 |
| `COM_RC_IN_MODE` | 0 | 1 | 实机要求/使用 RC 输入；SITL 默认不要求 RC 校准配置。 | 如果主要跑 OFFBOARD/MAVROS，不建议导入 |
| `COM_DL_LOSS_T` | 5 | 10 | 数据链路丢失超时更短。 | 可导入，但要确认仿真网络和 MAVROS 链路稳定 |
| `COM_LOW_BAT_ACT` | 2 | 0 | 低电动作不同。 | 若要模拟真实低电保护，导入 |
| `RTL_RETURN_ALT` | 20 | 30 | 返航高度不同。 | 可导入任务 profile |
| `RTL_DESCEND_ALT` | 20 | 10 | 返航下降高度不同。 | 可导入任务 profile |
| `MIS_TAKEOFF_ALT` | 1.5 | 2.5 | 任务起飞高度不同。 | 可导入任务 profile |
| `SDLOG_PROFILE` | 1023 | 131 | 实机日志记录更全。 | 仿真调试可导入；常规 CI/自动测试不建议，避免日志膨胀 |

## 不建议直接导入的参数

这些参数来自真实硬件环境，直接导入 SITL 通常没有收益，甚至会让仿真启动失败或行为不稳定。

### 1. 传感器标定参数

包括：

```text
CAL_ACC*
CAL_GYRO*
CAL_MAG*
SENS_BOARD_*
SENS_DPRES_OFF
```

含义是实物传感器 ID、优先级、安装旋转、零偏、比例系数。SITL 里的 IMU/mag 是模拟设备，`rcS` 会设置模拟传感器 ID，例如：

```text
CAL_ACC0_ID  = 1310988
CAL_GYRO0_ID = 1310988
CAL_MAG0_ID  = 197388
```

如果把实物的 `CAL_*_ID` 灌进去，PX4 可能认为当前模拟传感器不是已标定传感器，反而触发校准/健康检查问题。

### 2. 串口、UAVCAN、板载外设参数

包括报告里 `missing_in_sim_metadata` 的大量项：

```text
SER_TEL1_BAUD
SER_TEL2_BAUD
UAVCAN_*
SENS_UWB_CFG
SENS_*_CFG
TEL_*
GPS_1_CONFIG
GPS_2_CONFIG
```

这些是实物飞控外设配置。当前 SITL metadata 里没有部分参数，说明它们不是这个 SITL 构建的可控对象，或者是板级/定制参数。不要放进 FS150 SITL 的默认参数文件。

### 3. `SYS_AUTOSTART=4011`

这个参数只在实物 airframe 存在时才有意义。当前 v1.12.3 SITL 的 `iris` 是 `10016_iris`。如果你后续要做 FS150 专用 airframe，有两种路线：

1. 保持 `PX4_SIM_MODEL=iris` / `SYS_AUTOSTART=10016`，只通过 `param_file` 覆盖控制、电源、任务、估计参数。
2. 新增 FS150 专用 airframe 文件，例如 `4011_fs150`，再让 `PX4_SIM_MODEL=fs150` 匹配它。

第一种更轻量，适合现在的 `gazebo_sim_fs150`；第二种更完整，但需要维护 PX4 启动脚本。

## 建议拆分成多个参数 profile

不要把 `fs150-mav_sys_id4.params` 原样全部导入 SITL。更合理的是拆成几类 profile：

### `fs150-control.params`

用于模拟飞控控制律和飞行手感：

```text
MC_PITCHRATE_D
MC_PITCHRATE_I
MC_PITCHRATE_P
MC_ROLLRATE_D
MC_ROLLRATE_I
MC_ROLLRATE_P
MPC_THR_HOVER
MPC_XY_VEL_D_ACC
MPC_MANTHR_MIN
IMU_GYRO_CUTOFF
IMU_DGYRO_CUTOFF
IMU_INTEG_RATE
```

### `fs150-power.params`

用于模拟电池和低电行为：

```text
BAT_N_CELLS
BAT_V_CHARGED
BAT_V_EMPTY
BAT_LOW_THR
BAT_CRIT_THR
BAT_EMERGEN_THR
COM_LOW_BAT_ACT
```

`BAT_V_DIV`、`BAT_A_PER_V` 这类 ADC 换算参数是否导入，要看 SITL 电池插件是否使用它们；通常不应作为第一批关键参数。

### `fs150-mission-failsafe.params`

用于模拟真实任务和失效保护策略：

```text
MIS_TAKEOFF_ALT
RTL_RETURN_ALT
RTL_DESCEND_ALT
RTL_LAND_DELAY
COM_DL_LOSS_T
COM_DISARM_LAND
COM_KILL_DISARM
NAV_DLL_ACT
```

### `fs150-vision-ekf.params`

只有在仿真里已经提供 VRPN/vision/external odometry 时使用：

```text
EKF2_AID_MASK
EKF2_HGT_MODE
EKF2_MAG_TYPE
EKF2_REQ_GPS_H
MAV_ODOM_LP
```

如果还没有外部定位数据流，先不要导入这组。

### `fs150-identity.params`

用于多机编号，不建议写死在通用包里：

```text
MAV_SYS_ID
MAV_0_MODE
MAV_0_RATE
MAV_1_MODE
MAV_1_FORWARD
```

更好的做法是 launch 中按 `ID` 动态生成 `MAV_SYS_ID`，例如第 4 架才设置为 4。

## 对 `gazebo_sim_fs150` 的封装建议

`gazebo_sim_fs150` 应该是轻量包，只维护：

```text
firmware/fs150-control.params
firmware/fs150-power.params
firmware/fs150-mission-failsafe.params
firmware/fs150-vision-ekf.params
models/fs150_iris.sdf
launch/fs150.launch
```

其中 `launch/fs150.launch` include 基础包的 `iris.launch`：

```xml
<include file="$(find gazebo_sim_px4_1_12)/launch/iris.launch">
  <arg name="vehicle" value="iris"/>
  <arg name="px4_sim_model" value="iris"/>
  <arg name="model_name" value="fs150_$(arg ID)"/>
  <arg name="ID" value="$(arg ID)"/>
  <arg name="work_dir" value="$(env HOME)/.xgc2/px4_sitl/fs150_$(arg ID)"/>
  <arg name="sdf" value="$(find gazebo_sim_fs150)/models/fs150_iris.sdf"/>
  <arg name="param_file" value="$(find gazebo_sim_fs150)/firmware/fs150-control.params"/>
  <arg name="reset_params" value="true"/>
</include>
```

如果需要同时加载多个 profile，基础启动脚本后续可以从单个 `param_file` 扩展为 `param_files`，或者在 wrapper 包里生成合并后的临时参数文件。

## Comparison Basis

- FS150 parameter file: `/home/lxk/Dev/xgc2-vibe-coding/xgc2-devops/products/ros1_dev/src/driver/fs-150/firmware/fs150-mav_sys_id4.params`
- Onboard parameters for Vehicle 4
- 
- Stack: PX4 Pro
- Vehicle: Multi-Rotor
- Version: 1.12.3 dev
- Git Revision: 6f468c6be5000008
- 
- Vehicle-Id Component-Id Name Value Type
- SITL runtime: `/opt/ros/noetic/share/px4_sitl_runtime_1_12/runtime`
- SITL model: `PX4_SIM_MODEL=iris` -> `etc/init.d-posix/airframes/10016_iris`
- SITL instance assumption: launch `ID=0`, so `MAV_SYS_ID=1` in the default baseline.
- Effective default model: metadata defaults from `parameters.json.xz`, then deterministic `rcS`, `rc.mc_defaults`, and `10016_iris` startup overrides. Conditional environment branches such as `PX4_ESTIMATOR` and `PX4_SIM_SPEED_FACTOR` are not applied.

## Summary

- FS150 exported params compared: 801
- PX4 v1.12.3 metadata/effective params available: 1462
- Same as SITL baseline: 631
- Different from SITL baseline: 122
- Exported by FS150 but missing from this SITL metadata: 48
- Present in SITL metadata/baseline but not exported by FS150: 709

## Different Parameter Families

| Family | Different Count | Missing In SITL Metadata |
| --- | ---: | ---: |
| Actuator output | 3 | 0 |
| Battery/power | 8 | 6 |
| Commander/failsafe | 10 | 0 |
| Estimator | 4 | 0 |
| GPS | 0 | 2 |
| IMU runtime | 3 | 0 |
| Logging | 3 | 0 |
| MAVLink/system identity | 6 | 3 |
| Mission | 1 | 0 |
| Multicopter attitude/rate | 6 | 0 |
| Multicopter position | 3 | 0 |
| Navigation | 1 | 0 |
| Other | 2 | 1 |
| RC/operator input | 23 | 0 |
| Return/landing | 3 | 0 |
| Safety circuit breaker | 1 | 0 |
| Sensor calibration | 38 | 0 |
| Sensor selection/offset | 6 | 18 |
| Serial port | 0 | 2 |
| System/autostart | 1 | 2 |
| Telemetry | 0 | 3 |
| UAVCAN | 0 | 11 |

## Interpretation By Family

- Sensor calibration differences are expected: FS150 exports real IMU/mag IDs, offsets, scales, priorities, and rotations; SITL uses simulated sensor IDs and mostly default calibration values.
- System identity differs: FS150 export is vehicle/component scoped for vehicle 4, while default SITL launch instance 0 becomes `MAV_SYS_ID=1`.
- Battery/power differences are real hardware configuration differences, especially cell count, voltage divider, current source/channel, and failsafe thresholds.
- Commander/navigation/control differences indicate operational tuning copied from the real vehicle, not just hardware calibration. These are the parameters most likely to change FS150-like simulation behavior.
- Parameters marked `missing_in_sim_metadata` are present in the FS150 export but not in this installed PX4 v1.12.3 SITL metadata table; they are likely board-specific, renamed, or build-specific. Verify before injecting them into SITL.

## Full FS150 Export Comparison

| # | Parameter | Family | FS150 | SITL iris default | Delta | Status | SITL source |
| ---: | --- | --- | ---: | ---: | ---: | --- | --- |
| 1 | `ASPD_SCALE` | Other | 1 | 1 | 0 | same | metadata default |
| 2 | `BAT1_A_PER_V` | Battery/power | 17 |  |  | missing_in_sim_metadata |  |
| 3 | `BAT1_CAPACITY` | Battery/power | -1 | -1 | 0 | same | metadata default |
| 4 | `BAT1_I_CHANNEL` | Battery/power | -1 |  |  | missing_in_sim_metadata |  |
| 5 | `BAT1_N_CELLS` | Battery/power | 3 | 0 | 3 | different | metadata default |
| 6 | `BAT1_R_INTERNAL` | Battery/power | -1 | -1 | 0 | same | metadata default |
| 7 | `BAT1_SOURCE` | Battery/power | 0 | 0 | 0 | same | metadata default |
| 8 | `BAT1_V_CHANNEL` | Battery/power | -1 |  |  | missing_in_sim_metadata |  |
| 9 | `BAT1_V_CHARGED` | Battery/power | 4.3499999 | 4.05 | 0.299999905 | different | metadata default |
| 10 | `BAT1_V_DIV` | Battery/power | 19.2690182 |  |  | missing_in_sim_metadata |  |
| 11 | `BAT1_V_EMPTY` | Battery/power | 3.5999999 | 3.5 | 0.0999999046 | different | metadata default |
| 12 | `BAT1_V_LOAD_DROP` | Battery/power | 0.300000012 | 0.3 | 1.1920929e-08 | same | metadata default |
| 13 | `BAT_ADC_CHANNEL` | Battery/power | -1 |  |  | missing_in_sim_metadata |  |
| 14 | `BAT_A_PER_V` | Battery/power | 17 | -1 | 18 | different | metadata default |
| 15 | `BAT_CAPACITY` | Battery/power | -1 | -1 | 0 | same | metadata default |
| 16 | `BAT_CRIT_THR` | Battery/power | 0.0700000003 | 0.07 | 2.98023217e-10 | same | metadata default |
| 17 | `BAT_EMERGEN_THR` | Battery/power | 0.0500000007 | 0.05 | 7.45058057e-10 | same | metadata default |
| 18 | `BAT_LOW_THR` | Battery/power | 0.150000006 | 0.15 | 5.96046448e-09 | same | metadata default |
| 19 | `BAT_N_CELLS` | Battery/power | 3 | 4 | -1 | different | rcS:129 set-default |
| 20 | `BAT_R_INTERNAL` | Battery/power | -1 | -1 | 0 | same | metadata default |
| 21 | `BAT_SOURCE` | Battery/power | 0 | 0 | 0 | same | metadata default |
| 22 | `BAT_V_CHARGED` | Battery/power | 4.3499999 | 4.05 | 0.299999905 | different | metadata default |
| 23 | `BAT_V_DIV` | Battery/power | 19.2690182 | -1 | 20.2690182 | different | metadata default |
| 24 | `BAT_V_EMPTY` | Battery/power | 3.5999999 | 3.5 | 0.0999999046 | different | metadata default |
| 25 | `BAT_V_LOAD_DROP` | Battery/power | 0.300000012 | 0.3 | 1.1920929e-08 | same | metadata default |
| 26 | `BAT_V_OFFS_CURR` | Battery/power | 0 |  |  | missing_in_sim_metadata |  |
| 27 | `CAL_ACC0_ID` | Sensor calibration | 6946826 | 1310988 | 5635838 | different | rcS simulated IMU calibration ID |
| 28 | `CAL_ACC0_PRIO` | Sensor calibration | 50 | -1 | 51 | different | metadata default |
| 29 | `CAL_ACC0_ROT` | Sensor calibration | -1 | -1 | 0 | same | metadata default |
| 30 | `CAL_ACC0_XOFF` | Sensor calibration | 0.0185580309 | 0 | 0.0185580309 | different | metadata default |
| 31 | `CAL_ACC0_XSCALE` | Sensor calibration | 0.994249225 | 1 | -0.00575077534 | different | metadata default |
| 32 | `CAL_ACC0_YOFF` | Sensor calibration | -0.152910233 | 0 | -0.152910233 | different | metadata default |
| 33 | `CAL_ACC0_YSCALE` | Sensor calibration | 0.991756856 | 1 | -0.00824314356 | different | metadata default |
| 34 | `CAL_ACC0_ZOFF` | Sensor calibration | -0.0654511452 | 0 | -0.0654511452 | different | metadata default |
| 35 | `CAL_ACC0_ZSCALE` | Sensor calibration | 0.996204019 | 1 | -0.00379598141 | different | metadata default |
| 36 | `CAL_ACC1_ID` | Sensor calibration | 2490378 | 1310996 | 1179382 | different | rcS simulated IMU calibration ID |
| 37 | `CAL_ACC1_PRIO` | Sensor calibration | 50 | -1 | 51 | different | metadata default |
| 38 | `CAL_ACC1_ROT` | Sensor calibration | -1 | -1 | 0 | same | metadata default |
| 39 | `CAL_ACC1_XOFF` | Sensor calibration | -0.000972270966 | 0 | -0.000972270966 | different | metadata default |
| 40 | `CAL_ACC1_XSCALE` | Sensor calibration | 1 | 1 | 0 | same | metadata default |
| 41 | `CAL_ACC1_YOFF` | Sensor calibration | 0.00307750702 | 0 | 0.00307750702 | different | metadata default |
| 42 | `CAL_ACC1_YSCALE` | Sensor calibration | 1 | 1 | 0 | same | metadata default |
| 43 | `CAL_ACC1_ZOFF` | Sensor calibration | 0.112415314 | 0 | 0.112415314 | different | metadata default |
| 44 | `CAL_ACC1_ZSCALE` | Sensor calibration | 1 | 1 | 0 | same | metadata default |
| 45 | `CAL_ACC2_ID` | Sensor calibration | 0 | 1311004 | -1311004 | different | rcS simulated IMU calibration ID |
| 46 | `CAL_ACC3_ID` | Sensor calibration | 0 | 0 | 0 | same | metadata default |
| 47 | `CAL_AIR_CMODEL` | Sensor calibration | 0 | 0 | 0 | same | metadata default |
| 48 | `CAL_AIR_TUBED_MM` | Sensor calibration | 1.5 | 1.5 | 0 | same | metadata default |
| 49 | `CAL_AIR_TUBELEN` | Sensor calibration | 0.200000003 | 0.2 | 2.98023223e-09 | same | metadata default |
| 50 | `CAL_GYRO0_ID` | Sensor calibration | 6684682 | 1310988 | 5373694 | different | rcS simulated IMU calibration ID |
| 51 | `CAL_GYRO0_PRIO` | Sensor calibration | 50 | -1 | 51 | different | metadata default |
| 52 | `CAL_GYRO0_ROT` | Sensor calibration | -1 | -1 | 0 | same | metadata default |
| 53 | `CAL_GYRO0_XOFF` | Sensor calibration | 0.0067607481 | 0 | 0.0067607481 | different | metadata default |
| 54 | `CAL_GYRO0_YOFF` | Sensor calibration | -0.00134988292 | 0 | -0.00134988292 | different | metadata default |
| 55 | `CAL_GYRO0_ZOFF` | Sensor calibration | 0.000827742217 | 0 | 0.000827742217 | different | metadata default |
| 56 | `CAL_GYRO1_ID` | Sensor calibration | 2490378 | 1310996 | 1179382 | different | rcS simulated IMU calibration ID |
| 57 | `CAL_GYRO1_PRIO` | Sensor calibration | 50 | -1 | 51 | different | metadata default |
| 58 | `CAL_GYRO1_ROT` | Sensor calibration | -1 | -1 | 0 | same | metadata default |
| 59 | `CAL_GYRO1_XOFF` | Sensor calibration | -0.00245844014 | 0 | -0.00245844014 | different | metadata default |
| 60 | `CAL_GYRO1_YOFF` | Sensor calibration | -0.0154654104 | 0 | -0.0154654104 | different | metadata default |
| 61 | `CAL_GYRO1_ZOFF` | Sensor calibration | 0.00347761041 | 0 | 0.00347761041 | different | metadata default |
| 62 | `CAL_GYRO2_ID` | Sensor calibration | 0 | 1311004 | -1311004 | different | rcS simulated IMU calibration ID |
| 63 | `CAL_GYRO3_ID` | Sensor calibration | 0 | 0 | 0 | same | metadata default |
| 64 | `CAL_MAG0_ID` | Sensor calibration | 396809 | 197388 | 199421 | different | rcS simulated mag calibration ID |
| 65 | `CAL_MAG0_PRIO` | Sensor calibration | 75 | -1 | 76 | different | metadata default |
| 66 | `CAL_MAG0_ROT` | Sensor calibration | 4 | -1 | 5 | different | metadata default |
| 67 | `CAL_MAG0_XCOMP` | Sensor calibration | 0 | 0 | 0 | same | metadata default |
| 68 | `CAL_MAG0_XODIAG` | Sensor calibration | 0.257161617 | 0 | 0.257161617 | different | metadata default |
| 69 | `CAL_MAG0_XOFF` | Sensor calibration | -1.20258224 | 0 | -1.20258224 | different | metadata default |
| 70 | `CAL_MAG0_XSCALE` | Sensor calibration | 0.622476101 | 1 | -0.377523899 | different | metadata default |
| 71 | `CAL_MAG0_YCOMP` | Sensor calibration | 0 | 0 | 0 | same | metadata default |
| 72 | `CAL_MAG0_YODIAG` | Sensor calibration | 0.0718506426 | 0 | 0.0718506426 | different | metadata default |
| 73 | `CAL_MAG0_YOFF` | Sensor calibration | 1.21656382 | 0 | 1.21656382 | different | metadata default |
| 74 | `CAL_MAG0_YSCALE` | Sensor calibration | 0.434656292 | 1 | -0.565343708 | different | metadata default |
| 75 | `CAL_MAG0_ZCOMP` | Sensor calibration | 0 | 0 | 0 | same | metadata default |
| 76 | `CAL_MAG0_ZODIAG` | Sensor calibration | -0.0938132033 | 0 | -0.0938132033 | different | metadata default |
| 77 | `CAL_MAG0_ZOFF` | Sensor calibration | 0.604580045 | 0 | 0.604580045 | different | metadata default |
| 78 | `CAL_MAG0_ZSCALE` | Sensor calibration | 0.514073431 | 1 | -0.485926569 | different | metadata default |
| 79 | `CAL_MAG1_ID` | Sensor calibration | 0 | 197644 | -197644 | different | rcS simulated mag calibration ID |
| 80 | `CAL_MAG1_ROT` | Sensor calibration | -1 | -1 | 0 | same | metadata default |
| 81 | `CAL_MAG2_ID` | Sensor calibration | 0 | 0 | 0 | same | metadata default |
| 82 | `CAL_MAG2_ROT` | Sensor calibration | -1 | -1 | 0 | same | metadata default |
| 83 | `CAL_MAG3_ID` | Sensor calibration | 0 | 0 | 0 | same | metadata default |
| 84 | `CAL_MAG3_ROT` | Sensor calibration | -1 | -1 | 0 | same | metadata default |
| 85 | `CAL_MAG_COMP_TYP` | Sensor calibration | 0 | 0 | 0 | same | metadata default |
| 86 | `CAL_MAG_ROT_AUTO` | Sensor calibration | 1 | 1 | 0 | same | metadata default |
| 87 | `CAL_MAG_SIDES` | Sensor calibration | 63 | 63 | 0 | same | metadata default |
| 88 | `CAM_CAP_FBACK` | Other | 0 | 0 | 0 | same | metadata default |
| 89 | `CBRK_AIRSPD_CHK` | Safety circuit breaker | 0 | 0 | 0 | same | rcS:131 set-default |
| 90 | `CBRK_BUZZER` | Safety circuit breaker | 0 | 0 | 0 | same | metadata default |
| 91 | `CBRK_ENGINEFAIL` | Safety circuit breaker | 284953 | 284953 | 0 | same | metadata default |
| 92 | `CBRK_FLIGHTTERM` | Safety circuit breaker | 121212 | 121212 | 0 | same | metadata default |
| 93 | `CBRK_RATE_CTRL` | Safety circuit breaker | 0 | 0 | 0 | same | metadata default |
| 94 | `CBRK_SUPPLY_CHK` | Safety circuit breaker | 0 | 894281 | -894281 | different | rcS:132 set-default |
| 95 | `CBRK_USB_CHK` | Safety circuit breaker | 197848 | 197848 | 0 | same | metadata default |
| 96 | `CBRK_VELPOSERR` | Safety circuit breaker | 0 | 0 | 0 | same | metadata default |
| 97 | `CBRK_VTOLARMING` | Safety circuit breaker | 0 | 0 | 0 | same | metadata default |
| 98 | `COM_ARM_AUTH_ID` | Commander/failsafe | 10 | 10 | 0 | same | metadata default |
| 99 | `COM_ARM_AUTH_MET` | Commander/failsafe | 0 | 0 | 0 | same | metadata default |
| 100 | `COM_ARM_AUTH_REQ` | Commander/failsafe | 0 | 0 | 0 | same | metadata default |
| 101 | `COM_ARM_AUTH_TO` | Commander/failsafe | 1 | 1 | 0 | same | metadata default |
| 102 | `COM_ARM_CHK_ESCS` | Commander/failsafe | 0 | 0 | 0 | same | metadata default |
| 103 | `COM_ARM_EKF_HGT` | Commander/failsafe | 1 | 1 | 0 | same | metadata default |
| 104 | `COM_ARM_EKF_POS` | Commander/failsafe | 0.5 | 0.5 | 0 | same | metadata default |
| 105 | `COM_ARM_EKF_VEL` | Commander/failsafe | 0.5 | 0.5 | 0 | same | metadata default |
| 106 | `COM_ARM_EKF_YAW` | Commander/failsafe | 0.5 | 0.5 | 0 | same | metadata default |
| 107 | `COM_ARM_IMU_ACC` | Commander/failsafe | 0.699999988 | 0.7 | -1.19209289e-08 | same | metadata default |
| 108 | `COM_ARM_IMU_GYR` | Commander/failsafe | 0.25 | 0.25 | 0 | same | metadata default |
| 109 | `COM_ARM_MAG_ANG` | Commander/failsafe | 45 | 45 | 0 | same | metadata default |
| 110 | `COM_ARM_MAG_STR` | Commander/failsafe | 1 | 1 | 0 | same | metadata default |
| 111 | `COM_ARM_MIS_REQ` | Commander/failsafe | 0 | 0 | 0 | same | metadata default |
| 112 | `COM_ARM_SDCARD` | Commander/failsafe | 1 | 1 | 0 | same | metadata default |
| 113 | `COM_ARM_SWISBTN` | Commander/failsafe | 0 | 0 | 0 | same | metadata default |
| 114 | `COM_ARM_WO_GPS` | Commander/failsafe | 1 | 1 | 0 | same | metadata default |
| 115 | `COM_CPU_MAX` | Commander/failsafe | 90 | -1 | 91 | different | rcS:135 set-default |
| 116 | `COM_DISARM_LAND` | Commander/failsafe | 1 | 2 | -1 | different | metadata default |
| 117 | `COM_DISARM_PRFLT` | Commander/failsafe | 10 | 10 | 0 | same | metadata default |
| 118 | `COM_DL_LOSS_T` | Commander/failsafe | 5 | 10 | -5 | different | metadata default |
| 119 | `COM_EF_C2T` | Commander/failsafe | 5 | 5 | 0 | same | metadata default |
| 120 | `COM_EF_THROT` | Commander/failsafe | 0.5 | 0.5 | 0 | same | metadata default |
| 121 | `COM_EF_TIME` | Commander/failsafe | 10 | 10 | 0 | same | metadata default |
| 122 | `COM_FLIGHT_UUID` | Commander/failsafe | 454 | 0 | 454 | different | metadata default |
| 123 | `COM_FLTMODE1` | Commander/failsafe | 8 | -1 | 9 | different | metadata default |
| 124 | `COM_FLTMODE2` | Commander/failsafe | -1 | -1 | 0 | same | metadata default |
| 125 | `COM_FLTMODE3` | Commander/failsafe | -1 | -1 | 0 | same | metadata default |
| 126 | `COM_FLTMODE4` | Commander/failsafe | 1 | -1 | 2 | different | metadata default |
| 127 | `COM_FLTMODE5` | Commander/failsafe | -1 | -1 | 0 | same | metadata default |
| 128 | `COM_FLTMODE6` | Commander/failsafe | 2 | -1 | 3 | different | metadata default |
| 129 | `COM_FLT_PROFILE` | Commander/failsafe | 0 | 0 | 0 | same | metadata default |
| 130 | `COM_HLDL_LOSS_T` | Commander/failsafe | 120 | 120 | 0 | same | metadata default |
| 131 | `COM_HLDL_REG_T` | Commander/failsafe | 0 | 0 | 0 | same | metadata default |
| 132 | `COM_HOME_H_T` | Commander/failsafe | 5 | 5 | 0 | same | metadata default |
| 133 | `COM_HOME_IN_AIR` | Commander/failsafe | 0 | 0 | 0 | same | metadata default |
| 134 | `COM_HOME_V_T` | Commander/failsafe | 10 | 10 | 0 | same | metadata default |
| 135 | `COM_KILL_DISARM` | Commander/failsafe | 0 | 5 | -5 | different | metadata default |
| 136 | `COM_LKDOWN_TKO` | Commander/failsafe | 3 | 3 | 0 | same | metadata default |
| 137 | `COM_LOW_BAT_ACT` | Commander/failsafe | 2 | 0 | 2 | different | metadata default |
| 138 | `COM_MOT_TEST_EN` | Commander/failsafe | 1 | 1 | 0 | same | metadata default |
| 139 | `COM_OBC_LOSS_T` | Commander/failsafe | 5 | 5 | 0 | same | metadata default |
| 140 | `COM_OBL_ACT` | Commander/failsafe | 0 | 0 | 0 | same | metadata default |
| 141 | `COM_OBL_RC_ACT` | Commander/failsafe | 0 | 0 | 0 | same | metadata default |
| 142 | `COM_OBS_AVOID` | Commander/failsafe | 0 | 0 | 0 | same | metadata default |
| 143 | `COM_OF_LOSS_T` | Commander/failsafe | 1 | 1 | 0 | same | metadata default |
| 144 | `COM_POSCTL_NAVL` | Commander/failsafe | 0 | 0 | 0 | same | metadata default |
| 145 | `COM_POS_FS_DELAY` | Commander/failsafe | 1 | 1 | 0 | same | metadata default |
| 146 | `COM_POS_FS_EPH` | Commander/failsafe | 5 | 5 | 0 | same | metadata default |
| 147 | `COM_POS_FS_EPV` | Commander/failsafe | 10 | 10 | 0 | same | metadata default |
| 148 | `COM_POS_FS_GAIN` | Commander/failsafe | 10 | 10 | 0 | same | metadata default |
| 149 | `COM_POS_FS_PROB` | Commander/failsafe | 30 | 30 | 0 | same | metadata default |
| 150 | `COM_POWER_COUNT` | Commander/failsafe | 1 | 1 | 0 | same | metadata default |
| 151 | `COM_PREARM_MODE` | Commander/failsafe | 0 | 0 | 0 | same | metadata default |
| 152 | `COM_RCL_ACT_T` | Commander/failsafe | 15 | 15 | 0 | same | metadata default |
| 153 | `COM_RCL_EXCEPT` | Commander/failsafe | 0 | 0 | 0 | same | metadata default |
| 154 | `COM_RC_ARM_HYST` | Commander/failsafe | 1000 | 1000 | 0 | same | metadata default |
| 155 | `COM_RC_IN_MODE` | Commander/failsafe | 0 | 1 | -1 | different | rcS:138 set-default |
| 156 | `COM_RC_LOSS_T` | Commander/failsafe | 0.5 | 0.5 | 0 | same | metadata default |
| 157 | `COM_RC_OVERRIDE` | Commander/failsafe | 1 | 1 | 0 | same | metadata default |
| 158 | `COM_RC_STICK_OV` | Commander/failsafe | 30 | 30 | 0 | same | metadata default |
| 159 | `COM_REARM_GRACE` | Commander/failsafe | 1 | 1 | 0 | same | metadata default |
| 160 | `COM_TAKEOFF_ACT` | Commander/failsafe | 0 | 0 | 0 | same | metadata default |
| 161 | `COM_VEL_FS_EVH` | Commander/failsafe | 1 | 1 | 0 | same | metadata default |
| 162 | `CP_DELAY` | Other | 0.400000006 | 0.4 | 5.96046446e-09 | same | metadata default |
| 163 | `CP_DIST` | Other | -1 | -1 | 0 | same | metadata default |
| 164 | `CP_GO_NO_DATA` | Other | 0 | 0 | 0 | same | metadata default |
| 165 | `CP_GUIDE_ANG` | Other | 30 | 30 | 0 | same | metadata default |
| 166 | `EKF2_ABIAS_INIT` | Estimator | 0.200000003 | 0.2 | 2.98023223e-09 | same | metadata default |
| 167 | `EKF2_ABL_ACCLIM` | Estimator | 25 | 25 | 0 | same | metadata default |
| 168 | `EKF2_ABL_GYRLIM` | Estimator | 3 | 3 | 0 | same | metadata default |
| 169 | `EKF2_ABL_LIM` | Estimator | 0.400000006 | 0.4 | 5.96046446e-09 | same | metadata default |
| 170 | `EKF2_ABL_TAU` | Estimator | 0.5 | 0.5 | 0 | same | metadata default |
| 171 | `EKF2_ACC_B_NOISE` | Estimator | 0.00300000003 | 0.003 | 2.6077032e-11 | same | metadata default |
| 172 | `EKF2_ACC_NOISE` | Estimator | 0.349999994 | 0.35 | -5.96046446e-09 | same | metadata default |
| 173 | `EKF2_AID_MASK` | Estimator | 24 | 1 | 23 | different | metadata default |
| 174 | `EKF2_ANGERR_INIT` | Estimator | 0.100000001 | 0.1 | 1.49011611e-09 | same | metadata default |
| 175 | `EKF2_ARSP_THR` | Estimator | 0 | 0 | 0 | same | metadata default |
| 176 | `EKF2_ASPD_MAX` | Estimator | 20 | 20 | 0 | same | metadata default |
| 177 | `EKF2_ASP_DELAY` | Estimator | 100 | 100 | 0 | same | metadata default |
| 178 | `EKF2_AVEL_DELAY` | Estimator | 5 | 5 | 0 | same | metadata default |
| 179 | `EKF2_BARO_DELAY` | Estimator | 0 | 0 | 0 | same | metadata default |
| 180 | `EKF2_BARO_GATE` | Estimator | 5 | 5 | 0 | same | metadata default |
| 181 | `EKF2_BARO_NOISE` | Estimator | 3.5 | 3.5 | 0 | same | metadata default |
| 182 | `EKF2_BCOEF_X` | Estimator | 25 | 25 | 0 | same | metadata default |
| 183 | `EKF2_BCOEF_Y` | Estimator | 25 | 25 | 0 | same | metadata default |
| 184 | `EKF2_BETA_GATE` | Estimator | 5 | 5 | 0 | same | metadata default |
| 185 | `EKF2_BETA_NOISE` | Estimator | 0.300000012 | 0.3 | 1.1920929e-08 | same | metadata default |
| 186 | `EKF2_DECL_TYPE` | Estimator | 7 | 7 | 0 | same | metadata default |
| 187 | `EKF2_DRAG_NOISE` | Estimator | 2.5 | 2.5 | 0 | same | metadata default |
| 188 | `EKF2_EAS_NOISE` | Estimator | 1.39999998 | 1.4 | -2.38418578e-08 | same | metadata default |
| 189 | `EKF2_EVA_NOISE` | Estimator | 0.0500000007 | 0.05 | 7.45058057e-10 | same | metadata default |
| 190 | `EKF2_EVP_GATE` | Estimator | 5 | 5 | 0 | same | metadata default |
| 191 | `EKF2_EVP_NOISE` | Estimator | 0.100000001 | 0.1 | 1.49011611e-09 | same | metadata default |
| 192 | `EKF2_EVV_GATE` | Estimator | 3 | 3 | 0 | same | metadata default |
| 193 | `EKF2_EVV_NOISE` | Estimator | 0.100000001 | 0.1 | 1.49011611e-09 | same | metadata default |
| 194 | `EKF2_EV_DELAY` | Estimator | 175 | 175 | 0 | same | metadata default |
| 195 | `EKF2_EV_NOISE_MD` | Estimator | 0 | 0 | 0 | same | metadata default |
| 196 | `EKF2_EV_POS_X` | Estimator | 0 | 0 | 0 | same | metadata default |
| 197 | `EKF2_EV_POS_Y` | Estimator | 0 | 0 | 0 | same | metadata default |
| 198 | `EKF2_EV_POS_Z` | Estimator | 0 | 0 | 0 | same | metadata default |
| 199 | `EKF2_FUSE_BETA` | Estimator | 0 | 0 | 0 | same | metadata default |
| 200 | `EKF2_GBIAS_INIT` | Estimator | 0.100000001 | 0.1 | 1.49011611e-09 | same | metadata default |
| 201 | `EKF2_GND_EFF_DZ` | Estimator | 4 | 4 | 0 | same | metadata default |
| 202 | `EKF2_GND_MAX_HGT` | Estimator | 0.5 | 0.5 | 0 | same | metadata default |
| 203 | `EKF2_GPS_CHECK` | Estimator | 245 | 245 | 0 | same | metadata default |
| 204 | `EKF2_GPS_DELAY` | Estimator | 110 | 110 | 0 | same | metadata default |
| 205 | `EKF2_GPS_POS_X` | Estimator | 0 | 0 | 0 | same | metadata default |
| 206 | `EKF2_GPS_POS_Y` | Estimator | 0 | 0 | 0 | same | metadata default |
| 207 | `EKF2_GPS_POS_Z` | Estimator | 0 | 0 | 0 | same | metadata default |
| 208 | `EKF2_GPS_P_GATE` | Estimator | 5 | 5 | 0 | same | metadata default |
| 209 | `EKF2_GPS_P_NOISE` | Estimator | 0.5 | 0.5 | 0 | same | metadata default |
| 210 | `EKF2_GPS_V_GATE` | Estimator | 5 | 5 | 0 | same | metadata default |
| 211 | `EKF2_GPS_V_NOISE` | Estimator | 0.300000012 | 0.3 | 1.1920929e-08 | same | metadata default |
| 212 | `EKF2_GSF_TAS` | Estimator | 15 | 15 | 0 | same | metadata default |
| 213 | `EKF2_GYR_B_NOISE` | Estimator | 0.00100000005 | 0.001 | 4.74974511e-11 | same | metadata default |
| 214 | `EKF2_GYR_NOISE` | Estimator | 0.0149999997 | 0.015 | -3.35276126e-10 | same | metadata default |
| 215 | `EKF2_HDG_GATE` | Estimator | 2.5999999 | 2.6 | -9.53674317e-08 | same | metadata default |
| 216 | `EKF2_HEAD_NOISE` | Estimator | 0.300000012 | 0.3 | 1.1920929e-08 | same | metadata default |
| 217 | `EKF2_HGT_MODE` | Estimator | 3 | 0 | 3 | different | metadata default |
| 218 | `EKF2_IMU_POS_X` | Estimator | 0 | 0 | 0 | same | metadata default |
| 219 | `EKF2_IMU_POS_Y` | Estimator | 0 | 0 | 0 | same | metadata default |
| 220 | `EKF2_IMU_POS_Z` | Estimator | 0 | 0 | 0 | same | metadata default |
| 221 | `EKF2_MAG_ACCLIM` | Estimator | 0.5 | 0.5 | 0 | same | metadata default |
| 222 | `EKF2_MAG_B_NOISE` | Estimator | 9.99999975e-05 | 0.0001 | -2.526212e-12 | same | metadata default |
| 223 | `EKF2_MAG_CHECK` | Estimator | 0 | 0 | 0 | same | metadata default |
| 224 | `EKF2_MAG_DECL` | Estimator | 0 | 0 | 0 | same | metadata default |
| 225 | `EKF2_MAG_DELAY` | Estimator | 0 | 0 | 0 | same | metadata default |
| 226 | `EKF2_MAG_E_NOISE` | Estimator | 0.00100000005 | 0.001 | 4.74974511e-11 | same | metadata default |
| 227 | `EKF2_MAG_GATE` | Estimator | 3 | 3 | 0 | same | metadata default |
| 228 | `EKF2_MAG_NOISE` | Estimator | 0.0500000007 | 0.05 | 7.45058057e-10 | same | metadata default |
| 229 | `EKF2_MAG_TYPE` | Estimator | 5 | 0 | 5 | different | metadata default |
| 230 | `EKF2_MAG_YAWLIM` | Estimator | 0.25 | 0.25 | 0 | same | metadata default |
| 231 | `EKF2_MIN_OBS_DT` | Estimator | 20 | 20 | 0 | same | metadata default |
| 232 | `EKF2_MIN_RNG` | Estimator | 0.100000001 | 0.1 | 1.49011611e-09 | same | metadata default |
| 233 | `EKF2_MOVE_TEST` | Estimator | 1 | 1 | 0 | same | metadata default |
| 234 | `EKF2_MULTI_IMU` | Estimator | 3 | 3 | 0 | same | rcS:144 set-default |
| 235 | `EKF2_NOAID_NOISE` | Estimator | 10 | 10 | 0 | same | metadata default |
| 236 | `EKF2_NOAID_TOUT` | Estimator | 5000000 | 5000000 | 0 | same | metadata default |
| 237 | `EKF2_OF_DELAY` | Estimator | 20 | 20 | 0 | same | metadata default |
| 238 | `EKF2_OF_GATE` | Estimator | 3 | 3 | 0 | same | metadata default |
| 239 | `EKF2_OF_N_MAX` | Estimator | 0.5 | 0.5 | 0 | same | metadata default |
| 240 | `EKF2_OF_N_MIN` | Estimator | 0.150000006 | 0.15 | 5.96046448e-09 | same | metadata default |
| 241 | `EKF2_OF_POS_X` | Estimator | 0 | 0 | 0 | same | metadata default |
| 242 | `EKF2_OF_POS_Y` | Estimator | 0 | 0 | 0 | same | metadata default |
| 243 | `EKF2_OF_POS_Z` | Estimator | 0 | 0 | 0 | same | metadata default |
| 244 | `EKF2_OF_QMIN` | Estimator | 1 | 1 | 0 | same | metadata default |
| 245 | `EKF2_PCOEF_XN` | Estimator | 0 | 0 | 0 | same | metadata default |
| 246 | `EKF2_PCOEF_XP` | Estimator | 0 | 0 | 0 | same | metadata default |
| 247 | `EKF2_PCOEF_YN` | Estimator | 0 | 0 | 0 | same | metadata default |
| 248 | `EKF2_PCOEF_YP` | Estimator | 0 | 0 | 0 | same | metadata default |
| 249 | `EKF2_PCOEF_Z` | Estimator | 0 | 0 | 0 | same | metadata default |
| 250 | `EKF2_REQ_EPH` | Estimator | 3 | 3 | 0 | same | metadata default |
| 251 | `EKF2_REQ_EPV` | Estimator | 5 | 5 | 0 | same | metadata default |
| 252 | `EKF2_REQ_GPS_H` | Estimator | 10 | 0.5 | 9.5 | different | rcS:141 set-default |
| 253 | `EKF2_REQ_HDRIFT` | Estimator | 0.100000001 | 0.1 | 1.49011611e-09 | same | metadata default |
| 254 | `EKF2_REQ_NSATS` | Estimator | 6 | 6 | 0 | same | metadata default |
| 255 | `EKF2_REQ_PDOP` | Estimator | 2.5 | 2.5 | 0 | same | metadata default |
| 256 | `EKF2_REQ_SACC` | Estimator | 0.5 | 0.5 | 0 | same | metadata default |
| 257 | `EKF2_REQ_VDRIFT` | Estimator | 0.200000003 | 0.2 | 2.98023223e-09 | same | metadata default |
| 258 | `EKF2_RNG_AID` | Estimator | 1 | 1 | 0 | same | metadata default |
| 259 | `EKF2_RNG_A_HMAX` | Estimator | 5 | 5 | 0 | same | metadata default |
| 260 | `EKF2_RNG_A_IGATE` | Estimator | 1 | 1 | 0 | same | metadata default |
| 261 | `EKF2_RNG_A_VMAX` | Estimator | 1 | 1 | 0 | same | metadata default |
| 262 | `EKF2_RNG_DELAY` | Estimator | 5 | 5 | 0 | same | metadata default |
| 263 | `EKF2_RNG_GATE` | Estimator | 5 | 5 | 0 | same | metadata default |
| 264 | `EKF2_RNG_NOISE` | Estimator | 0.100000001 | 0.1 | 1.49011611e-09 | same | metadata default |
| 265 | `EKF2_RNG_PITCH` | Estimator | 0 | 0 | 0 | same | metadata default |
| 266 | `EKF2_RNG_POS_X` | Estimator | 0 | 0 | 0 | same | metadata default |
| 267 | `EKF2_RNG_POS_Y` | Estimator | 0 | 0 | 0 | same | metadata default |
| 268 | `EKF2_RNG_POS_Z` | Estimator | 0 | 0 | 0 | same | metadata default |
| 269 | `EKF2_RNG_QLTY_T` | Estimator | 1 | 1 | 0 | same | metadata default |
| 270 | `EKF2_RNG_SFE` | Estimator | 0.0500000007 | 0.05 | 7.45058057e-10 | same | metadata default |
| 271 | `EKF2_SEL_ERR_RED` | Estimator | 0.200000003 | 0.2 | 2.98023223e-09 | same | metadata default |
| 272 | `EKF2_SEL_IMU_ACC` | Estimator | 1 | 1 | 0 | same | metadata default |
| 273 | `EKF2_SEL_IMU_ANG` | Estimator | 15 | 15 | 0 | same | metadata default |
| 274 | `EKF2_SEL_IMU_RAT` | Estimator | 7 | 7 | 0 | same | metadata default |
| 275 | `EKF2_SEL_IMU_VEL` | Estimator | 2 | 2 | 0 | same | metadata default |
| 276 | `EKF2_SYNT_MAG_Z` | Estimator | 0 | 0 | 0 | same | metadata default |
| 277 | `EKF2_TAS_GATE` | Estimator | 3 | 3 | 0 | same | metadata default |
| 278 | `EKF2_TAU_POS` | Estimator | 0.25 | 0.25 | 0 | same | metadata default |
| 279 | `EKF2_TAU_VEL` | Estimator | 0.25 | 0.25 | 0 | same | metadata default |
| 280 | `EKF2_TERR_GRAD` | Estimator | 0.5 | 0.5 | 0 | same | metadata default |
| 281 | `EKF2_TERR_MASK` | Estimator | 3 | 3 | 0 | same | metadata default |
| 282 | `EKF2_TERR_NOISE` | Estimator | 5 | 5 | 0 | same | metadata default |
| 283 | `EKF2_WIND_NOISE` | Estimator | 0.100000001 | 0.1 | 1.49011611e-09 | same | metadata default |
| 284 | `EV_TSK_RC_LOSS` | Other | 0 | 0 | 0 | same | metadata default |
| 285 | `EV_TSK_STAT_DIS` | Other | 0 | 0 | 0 | same | metadata default |
| 286 | `FD_ESCS_EN` | Other | 1 | 1 | 0 | same | metadata default |
| 287 | `FD_EXT_ATS_EN` | Other | 0 | 0 | 0 | same | metadata default |
| 288 | `FD_EXT_ATS_TRIG` | Other | 1900 | 1900 | 0 | same | metadata default |
| 289 | `FD_FAIL_P` | Other | 60 | 60 | 0 | same | metadata default |
| 290 | `FD_FAIL_P_TTRI` | Other | 0.300000012 | 0.3 | 1.1920929e-08 | same | metadata default |
| 291 | `FD_FAIL_R` | Other | 60 | 60 | 0 | same | metadata default |
| 292 | `FD_FAIL_R_TTRI` | Other | 0.300000012 | 0.3 | 1.1920929e-08 | same | metadata default |
| 293 | `GF_ACTION` | Geofence | 2 | 2 | 0 | same | metadata default |
| 294 | `GF_ALTMODE` | Geofence | 0 | 0 | 0 | same | metadata default |
| 295 | `GF_COUNT` | Geofence | -1 | -1 | 0 | same | metadata default |
| 296 | `GF_MAX_HOR_DIST` | Geofence | 0 | 0 | 0 | same | metadata default |
| 297 | `GF_MAX_VER_DIST` | Geofence | 0 | 0 | 0 | same | metadata default |
| 298 | `GF_SOURCE` | Geofence | 0 | 0 | 0 | same | metadata default |
| 299 | `GPS_1_CONFIG` | GPS | 0 |  |  | missing_in_sim_metadata |  |
| 300 | `GPS_2_CONFIG` | GPS | 0 |  |  | missing_in_sim_metadata |  |
| 301 | `GPS_DUMP_COMM` | GPS | 0 | 0 | 0 | same | metadata default |
| 302 | `GPS_YAW_OFFSET` | GPS | 0 | 0 | 0 | same | metadata default |
| 303 | `HTE_ACC_GATE` | Other | 3 | 3 | 0 | same | metadata default |
| 304 | `HTE_HT_ERR_INIT` | Other | 0.100000001 | 0.1 | 1.49011611e-09 | same | metadata default |
| 305 | `HTE_HT_NOISE` | Other | 0.00359999994 | 0.0036 | -6.18398189e-11 | same | metadata default |
| 306 | `IMU_ACCEL_CUTOFF` | IMU runtime | 30 | 30 | 0 | same | metadata default |
| 307 | `IMU_DGYRO_CUTOFF` | IMU runtime | 35 | 30 | 5 | different | metadata default |
| 308 | `IMU_GYRO_CAL_EN` | IMU runtime | 1 | 1 | 0 | same | metadata default |
| 309 | `IMU_GYRO_CUTOFF` | IMU runtime | 35 | 40 | -5 | different | metadata default |
| 310 | `IMU_GYRO_DYN_NF` | IMU runtime | 0 | 0 | 0 | same | metadata default |
| 311 | `IMU_GYRO_FFT_EN` | IMU runtime | 1 | 1 | 0 | same | rcS:149 set-default |
| 312 | `IMU_GYRO_FFT_LEN` | IMU runtime | 1024 | 1024 | 0 | same | metadata default |
| 313 | `IMU_GYRO_FFT_MAX` | IMU runtime | 192 | 192 | 0 | same | metadata default |
| 314 | `IMU_GYRO_FFT_MIN` | IMU runtime | 32 | 32 | 0 | same | metadata default |
| 315 | `IMU_GYRO_NF_BW` | IMU runtime | 20 | 20 | 0 | same | metadata default |
| 316 | `IMU_GYRO_NF_FREQ` | IMU runtime | 0 | 0 | 0 | same | metadata default |
| 317 | `IMU_GYRO_RATEMAX` | IMU runtime | 800 | 800 | 0 | same | rc.mc_defaults:10 set-default |
| 318 | `IMU_INTEG_RATE` | IMU runtime | 200 | 250 | -50 | different | rcS simulator IMU integration rate |
| 319 | `LED_RGB2_MAXBRT` | Other | 31 |  |  | missing_in_sim_metadata |  |
| 320 | `LNDMC_ALT_GND` | Other | -1 | -1 | 0 | same | metadata default |
| 321 | `LNDMC_ALT_MAX` | Other | -1 | -1 | 0 | same | metadata default |
| 322 | `LNDMC_ROT_MAX` | Other | 20 | 20 | 0 | same | metadata default |
| 323 | `LNDMC_TRIG_TIME` | Other | 1 | 1 | 0 | same | metadata default |
| 324 | `LNDMC_XY_VEL_MAX` | Other | 1.5 | 1.5 | 0 | same | metadata default |
| 325 | `LNDMC_Z_VEL_MAX` | Other | 0.5 | 0.5 | 0 | same | metadata default |
| 326 | `LND_FLIGHT_T_HI` | Other | 7 | 0 | 7 | different | metadata default |
| 327 | `LND_FLIGHT_T_LO` | Other | -359431728 | 0 | -359431728 | different | metadata default |
| 328 | `MAV_0_CONFIG` | MAVLink/system identity | 101 |  |  | missing_in_sim_metadata |  |
| 329 | `MAV_0_FORWARD` | MAVLink/system identity | 1 | 1 | 0 | same | metadata default |
| 330 | `MAV_0_MODE` | MAVLink/system identity | 1 | 0 | 1 | different | metadata default |
| 331 | `MAV_0_RADIO_CTL` | MAVLink/system identity | 1 | 1 | 0 | same | metadata default |
| 332 | `MAV_0_RATE` | MAVLink/system identity | 0 | 1200 | -1200 | different | metadata default |
| 333 | `MAV_1_CONFIG` | MAVLink/system identity | 102 |  |  | missing_in_sim_metadata |  |
| 334 | `MAV_1_FORWARD` | MAVLink/system identity | 1 | 0 | 1 | different | metadata default |
| 335 | `MAV_1_MODE` | MAVLink/system identity | 0 | 2 | -2 | different | metadata default |
| 336 | `MAV_1_RADIO_CTL` | MAVLink/system identity | 1 | 1 | 0 | same | metadata default |
| 337 | `MAV_1_RATE` | MAVLink/system identity | 0 | 0 | 0 | same | metadata default |
| 338 | `MAV_2_CONFIG` | MAVLink/system identity | 0 |  |  | missing_in_sim_metadata |  |
| 339 | `MAV_COMP_ID` | MAVLink/system identity | 1 | 1 | 0 | same | metadata default |
| 340 | `MAV_FWDEXTSP` | MAVLink/system identity | 1 | 1 | 0 | same | metadata default |
| 341 | `MAV_HASH_CHK_EN` | MAVLink/system identity | 1 | 1 | 0 | same | metadata default |
| 342 | `MAV_HB_FORW_EN` | MAVLink/system identity | 1 | 1 | 0 | same | metadata default |
| 343 | `MAV_ODOM_LP` | MAVLink/system identity | 1 | 0 | 1 | different | metadata default |
| 344 | `MAV_PROTO_VER` | MAVLink/system identity | 0 | 0 | 0 | same | metadata default |
| 345 | `MAV_RADIO_TOUT` | MAVLink/system identity | 5 | 5 | 0 | same | metadata default |
| 346 | `MAV_SIK_RADIO_ID` | MAVLink/system identity | 0 | 0 | 0 | same | metadata default |
| 347 | `MAV_SYS_ID` | MAVLink/system identity | 4 | 1 | 3 | different | rcS set MAV_SYS_ID px4_instance+1, launch ID=0 |
| 348 | `MAV_TYPE` | MAVLink/system identity | 2 | 2 | 0 | same | metadata default |
| 349 | `MAV_USEHILGPS` | MAVLink/system identity | 0 | 0 | 0 | same | metadata default |
| 350 | `MC_ACRO_EXPO` | Multicopter attitude/rate | 0.689999998 | 0.69 | -2.38418574e-09 | same | metadata default |
| 351 | `MC_ACRO_EXPO_Y` | Multicopter attitude/rate | 0.689999998 | 0.69 | -2.38418574e-09 | same | metadata default |
| 352 | `MC_ACRO_P_MAX` | Multicopter attitude/rate | 720 | 720 | 0 | same | metadata default |
| 353 | `MC_ACRO_R_MAX` | Multicopter attitude/rate | 720 | 720 | 0 | same | metadata default |
| 354 | `MC_ACRO_SUPEXPO` | Multicopter attitude/rate | 0.699999988 | 0.7 | -1.19209289e-08 | same | metadata default |
| 355 | `MC_ACRO_SUPEXPOY` | Multicopter attitude/rate | 0.699999988 | 0.7 | -1.19209289e-08 | same | metadata default |
| 356 | `MC_ACRO_Y_MAX` | Multicopter attitude/rate | 540 | 540 | 0 | same | metadata default |
| 357 | `MC_AIRMODE` | Multicopter attitude/rate | 0 | 0 | 0 | same | metadata default |
| 358 | `MC_BAT_SCALE_EN` | Multicopter attitude/rate | 0 | 0 | 0 | same | metadata default |
| 359 | `MC_MAN_TILT_TAU` | Multicopter attitude/rate | 0 | 0 | 0 | same | metadata default |
| 360 | `MC_PITCHRATE_D` | Multicopter attitude/rate | 0.00100000005 | 0.003 | -0.00199999995 | different | metadata default |
| 361 | `MC_PITCHRATE_FF` | Multicopter attitude/rate | 0 | 0 | 0 | same | metadata default |
| 362 | `MC_PITCHRATE_I` | Multicopter attitude/rate | 0.0500000007 | 0.2 | -0.149999999 | different | metadata default |
| 363 | `MC_PITCHRATE_K` | Multicopter attitude/rate | 1 | 1 | 0 | same | metadata default |
| 364 | `MC_PITCHRATE_MAX` | Multicopter attitude/rate | 220 | 220 | 0 | same | metadata default |
| 365 | `MC_PITCHRATE_P` | Multicopter attitude/rate | 0.0700000003 | 0.15 | -0.0799999997 | different | metadata default |
| 366 | `MC_PITCH_P` | Multicopter attitude/rate | 6.5 | 6.5 | 0 | same | metadata default |
| 367 | `MC_PR_INT_LIM` | Multicopter attitude/rate | 0.300000012 | 0.3 | 1.1920929e-08 | same | metadata default |
| 368 | `MC_ROLLRATE_D` | Multicopter attitude/rate | 0.00100000005 | 0.003 | -0.00199999995 | different | metadata default |
| 369 | `MC_ROLLRATE_FF` | Multicopter attitude/rate | 0 | 0 | 0 | same | metadata default |
| 370 | `MC_ROLLRATE_I` | Multicopter attitude/rate | 0.0700000003 | 0.2 | -0.13 | different | metadata default |
| 371 | `MC_ROLLRATE_K` | Multicopter attitude/rate | 1 | 1 | 0 | same | metadata default |
| 372 | `MC_ROLLRATE_MAX` | Multicopter attitude/rate | 220 | 220 | 0 | same | metadata default |
| 373 | `MC_ROLLRATE_P` | Multicopter attitude/rate | 0.0700000003 | 0.15 | -0.0799999997 | different | metadata default |
| 374 | `MC_ROLL_P` | Multicopter attitude/rate | 6.5 | 6.5 | 0 | same | metadata default |
| 375 | `MC_RR_INT_LIM` | Multicopter attitude/rate | 0.300000012 | 0.3 | 1.1920929e-08 | same | metadata default |
| 376 | `MC_YAWRATE_D` | Multicopter attitude/rate | 0 | 0 | 0 | same | metadata default |
| 377 | `MC_YAWRATE_FF` | Multicopter attitude/rate | 0 | 0 | 0 | same | metadata default |
| 378 | `MC_YAWRATE_I` | Multicopter attitude/rate | 0.100000001 | 0.1 | 1.49011611e-09 | same | metadata default |
| 379 | `MC_YAWRATE_K` | Multicopter attitude/rate | 1 | 1 | 0 | same | metadata default |
| 380 | `MC_YAWRATE_MAX` | Multicopter attitude/rate | 200 | 200 | 0 | same | metadata default |
| 381 | `MC_YAWRATE_P` | Multicopter attitude/rate | 0.200000003 | 0.2 | 2.98023223e-09 | same | metadata default |
| 382 | `MC_YAW_P` | Multicopter attitude/rate | 2.79999995 | 2.8 | -4.76837156e-08 | same | metadata default |
| 383 | `MC_YAW_WEIGHT` | Multicopter attitude/rate | 0.400000006 | 0.4 | 5.96046446e-09 | same | metadata default |
| 384 | `MC_YR_INT_LIM` | Multicopter attitude/rate | 0.300000012 | 0.3 | 1.1920929e-08 | same | metadata default |
| 385 | `MIS_DIST_1WP` | Mission | 900 | 900 | 0 | same | metadata default |
| 386 | `MIS_DIST_WPS` | Mission | 900 | 900 | 0 | same | metadata default |
| 387 | `MIS_LTRMIN_ALT` | Mission | -1 | -1 | 0 | same | metadata default |
| 388 | `MIS_MNT_YAW_CTL` | Mission | 0 | 0 | 0 | same | metadata default |
| 389 | `MIS_TAKEOFF_ALT` | Mission | 1.5 | 2.5 | -1 | different | metadata default |
| 390 | `MIS_TAKEOFF_REQ` | Mission | 0 | 0 | 0 | same | metadata default |
| 391 | `MIS_YAW_ERR` | Mission | 12 | 12 | 0 | same | metadata default |
| 392 | `MIS_YAW_TMT` | Mission | -1 | -1 | 0 | same | metadata default |
| 393 | `MNT_MODE_IN` | Mount/gimbal | -1 | -1 | 0 | same | metadata default |
| 394 | `MOT_ORDERING` | Other | 0 | 0 | 0 | same | metadata default |
| 395 | `MOT_SLEW_MAX` | Other | 0 | 0 | 0 | same | metadata default |
| 396 | `MPC_ACC_DOWN_MAX` | Multicopter position | 3 | 3 | 0 | same | metadata default |
| 397 | `MPC_ACC_HOR` | Multicopter position | 3 | 3 | 0 | same | metadata default |
| 398 | `MPC_ACC_HOR_MAX` | Multicopter position | 5 | 5 | 0 | same | metadata default |
| 399 | `MPC_ACC_UP_MAX` | Multicopter position | 4 | 4 | 0 | same | metadata default |
| 400 | `MPC_ALT_MODE` | Multicopter position | 0 | 0 | 0 | same | metadata default |
| 401 | `MPC_HOLD_DZ` | Multicopter position | 0.100000001 | 0.1 | 1.49011611e-09 | same | metadata default |
| 402 | `MPC_HOLD_MAX_XY` | Multicopter position | 0.800000012 | 0.8 | 1.19209289e-08 | same | metadata default |
| 403 | `MPC_HOLD_MAX_Z` | Multicopter position | 0.600000024 | 0.6 | 2.38418579e-08 | same | metadata default |
| 404 | `MPC_JERK_AUTO` | Multicopter position | 4 | 4 | 0 | same | metadata default |
| 405 | `MPC_JERK_MAX` | Multicopter position | 8 | 8 | 0 | same | metadata default |
| 406 | `MPC_LAND_ALT1` | Multicopter position | 10 | 10 | 0 | same | metadata default |
| 407 | `MPC_LAND_ALT2` | Multicopter position | 5 | 5 | 0 | same | metadata default |
| 408 | `MPC_LAND_RC_HELP` | Multicopter position | 0 | 0 | 0 | same | metadata default |
| 409 | `MPC_LAND_SPEED` | Multicopter position | 0.699999988 | 0.7 | -1.19209289e-08 | same | metadata default |
| 410 | `MPC_MANTHR_MIN` | Multicopter position | 0.0399999991 | 0.08 | -0.0400000009 | different | metadata default |
| 411 | `MPC_MAN_TILT_MAX` | Multicopter position | 35 | 35 | 0 | same | metadata default |
| 412 | `MPC_MAN_Y_MAX` | Multicopter position | 150 | 150 | 0 | same | metadata default |
| 413 | `MPC_MAN_Y_TAU` | Multicopter position | 0.0799999982 | 0.08 | -1.78813934e-09 | same | metadata default |
| 414 | `MPC_POS_MODE` | Multicopter position | 4 | 4 | 0 | same | metadata default |
| 415 | `MPC_SPOOLUP_TIME` | Multicopter position | 1 | 1 | 0 | same | metadata default |
| 416 | `MPC_THR_CURVE` | Multicopter position | 0 | 0 | 0 | same | metadata default |
| 417 | `MPC_THR_HOVER` | Multicopter position | 0.360000014 | 0.5 | -0.139999986 | different | metadata default |
| 418 | `MPC_THR_MAX` | Multicopter position | 1 | 1 | 0 | same | metadata default |
| 419 | `MPC_THR_MIN` | Multicopter position | 0.119999997 | 0.12 | -2.68220901e-09 | same | metadata default |
| 420 | `MPC_TILTMAX_AIR` | Multicopter position | 45 | 45 | 0 | same | metadata default |
| 421 | `MPC_TILTMAX_LND` | Multicopter position | 12 | 12 | 0 | same | metadata default |
| 422 | `MPC_TKO_RAMP_T` | Multicopter position | 3 | 3 | 0 | same | metadata default |
| 423 | `MPC_TKO_SPEED` | Multicopter position | 1.5 | 1.5 | 0 | same | metadata default |
| 424 | `MPC_USE_HTE` | Multicopter position | 1 | 1 | 0 | same | metadata default |
| 425 | `MPC_VELD_LP` | Multicopter position | 5 | 5 | 0 | same | metadata default |
| 426 | `MPC_VEL_MANUAL` | Multicopter position | 10 | 10 | 0 | same | metadata default |
| 427 | `MPC_XY_CRUISE` | Multicopter position | 5 | 5 | 0 | same | metadata default |
| 428 | `MPC_XY_ERR_MAX` | Multicopter position | 2 | 2 | 0 | same | metadata default |
| 429 | `MPC_XY_MAN_EXPO` | Multicopter position | 0.600000024 | 0.6 | 2.38418579e-08 | same | metadata default |
| 430 | `MPC_XY_P` | Multicopter position | 0.949999988 | 0.95 | -1.19209289e-08 | same | metadata default |
| 431 | `MPC_XY_TRAJ_P` | Multicopter position | 0.5 | 0.5 | 0 | same | metadata default |
| 432 | `MPC_XY_VEL_ALL` | Multicopter position | -10 | -10 | 0 | same | metadata default |
| 433 | `MPC_XY_VEL_D_ACC` | Multicopter position | 0.25 | 0.2 | 0.05 | different | metadata default |
| 434 | `MPC_XY_VEL_I_ACC` | Multicopter position | 0.400000006 | 0.4 | 5.96046446e-09 | same | metadata default |
| 435 | `MPC_XY_VEL_MAX` | Multicopter position | 12 | 12 | 0 | same | metadata default |
| 436 | `MPC_XY_VEL_P_ACC` | Multicopter position | 1.79999995 | 1.8 | -4.76837159e-08 | same | metadata default |
| 437 | `MPC_YAWRAUTO_MAX` | Multicopter position | 45 | 45 | 0 | same | metadata default |
| 438 | `MPC_YAW_EXPO` | Multicopter position | 0.600000024 | 0.6 | 2.38418579e-08 | same | metadata default |
| 439 | `MPC_YAW_MODE` | Multicopter position | 0 | 0 | 0 | same | metadata default |
| 440 | `MPC_Z_MAN_EXPO` | Multicopter position | 0.600000024 | 0.6 | 2.38418579e-08 | same | metadata default |
| 441 | `MPC_Z_P` | Multicopter position | 1 | 1 | 0 | same | metadata default |
| 442 | `MPC_Z_VEL_ALL` | Multicopter position | -3 | -3 | 0 | same | metadata default |
| 443 | `MPC_Z_VEL_D_ACC` | Multicopter position | 0 | 0 | 0 | same | metadata default |
| 444 | `MPC_Z_VEL_I_ACC` | Multicopter position | 2 | 2 | 0 | same | metadata default |
| 445 | `MPC_Z_VEL_MAX_DN` | Multicopter position | 1 | 1 | 0 | same | metadata default |
| 446 | `MPC_Z_VEL_MAX_UP` | Multicopter position | 3 | 3 | 0 | same | metadata default |
| 447 | `MPC_Z_VEL_P_ACC` | Multicopter position | 4 | 4 | 0 | same | metadata default |
| 448 | `NAV_ACC_RAD` | Navigation | 2 | 2 | 0 | same | rc.mc_defaults:12 set-default |
| 449 | `NAV_DLL_ACT` | Navigation | 2 | 0 | 2 | different | metadata default |
| 450 | `NAV_FORCE_VT` | Navigation | 1 | 1 | 0 | same | metadata default |
| 451 | `NAV_FT_DST` | Navigation | 8 | 8 | 0 | same | metadata default |
| 452 | `NAV_FT_FS` | Navigation | 1 | 1 | 0 | same | metadata default |
| 453 | `NAV_FT_RS` | Navigation | 0.5 | 0.5 | 0 | same | metadata default |
| 454 | `NAV_FW_ALTL_RAD` | Navigation | 5 | 5 | 0 | same | metadata default |
| 455 | `NAV_FW_ALT_RAD` | Navigation | 10 | 10 | 0 | same | metadata default |
| 456 | `NAV_GPSF_LT` | Navigation | 0 | 0 | 0 | same | metadata default |
| 457 | `NAV_GPSF_P` | Navigation | 0 | 0 | 0 | same | metadata default |
| 458 | `NAV_GPSF_R` | Navigation | 15 | 15 | 0 | same | metadata default |
| 459 | `NAV_GPSF_TR` | Navigation | 0 | 0 | 0 | same | metadata default |
| 460 | `NAV_LOITER_RAD` | Navigation | 50 | 50 | 0 | same | metadata default |
| 461 | `NAV_MC_ALT_RAD` | Navigation | 0.800000012 | 0.8 | 1.19209289e-08 | same | metadata default |
| 462 | `NAV_MIN_FT_HT` | Navigation | 8 | 8 | 0 | same | metadata default |
| 463 | `NAV_RCL_ACT` | Navigation | 2 | 2 | 0 | same | metadata default |
| 464 | `NAV_TRAFF_AVOID` | Navigation | 1 | 1 | 0 | same | metadata default |
| 465 | `NAV_TRAFF_A_RADM` | Navigation | 500 | 500 | 0 | same | metadata default |
| 466 | `NAV_TRAFF_A_RADU` | Navigation | 10 | 10 | 0 | same | metadata default |
| 467 | `PLD_BTOUT` | Other | 5 | 5 | 0 | same | metadata default |
| 468 | `PLD_FAPPR_ALT` | Other | 0.100000001 | 0.1 | 1.49011611e-09 | same | metadata default |
| 469 | `PLD_HACC_RAD` | Other | 0.200000003 | 0.2 | 2.98023223e-09 | same | metadata default |
| 470 | `PLD_MAX_SRCH` | Other | 3 | 3 | 0 | same | metadata default |
| 471 | `PLD_SRCH_ALT` | Other | 10 | 10 | 0 | same | metadata default |
| 472 | `PLD_SRCH_TOUT` | Other | 10 | 10 | 0 | same | metadata default |
| 473 | `PWM_AUX_DIS1` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 474 | `PWM_AUX_DIS2` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 475 | `PWM_AUX_DIS3` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 476 | `PWM_AUX_DIS4` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 477 | `PWM_AUX_DIS5` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 478 | `PWM_AUX_DIS6` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 479 | `PWM_AUX_DISARM` | Actuator output | 1500 | 1500 | 0 | same | metadata default |
| 480 | `PWM_AUX_FAIL1` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 481 | `PWM_AUX_FAIL2` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 482 | `PWM_AUX_FAIL3` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 483 | `PWM_AUX_FAIL4` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 484 | `PWM_AUX_FAIL5` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 485 | `PWM_AUX_FAIL6` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 486 | `PWM_AUX_MAX` | Actuator output | 2000 | 2000 | 0 | same | metadata default |
| 487 | `PWM_AUX_MAX1` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 488 | `PWM_AUX_MAX2` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 489 | `PWM_AUX_MAX3` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 490 | `PWM_AUX_MAX4` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 491 | `PWM_AUX_MAX5` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 492 | `PWM_AUX_MAX6` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 493 | `PWM_AUX_MIN` | Actuator output | 1000 | 1000 | 0 | same | metadata default |
| 494 | `PWM_AUX_MIN1` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 495 | `PWM_AUX_MIN2` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 496 | `PWM_AUX_MIN3` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 497 | `PWM_AUX_MIN4` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 498 | `PWM_AUX_MIN5` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 499 | `PWM_AUX_MIN6` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 500 | `PWM_AUX_OUT` | Actuator output | 1234 | 0 | 1234 | different | metadata default |
| 501 | `PWM_AUX_RATE` | Actuator output | 50 | 50 | 0 | same | metadata default |
| 502 | `PWM_AUX_REV1` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 503 | `PWM_AUX_REV2` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 504 | `PWM_AUX_REV3` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 505 | `PWM_AUX_REV4` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 506 | `PWM_AUX_REV5` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 507 | `PWM_AUX_REV6` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 508 | `PWM_AUX_TRIM1` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 509 | `PWM_AUX_TRIM2` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 510 | `PWM_AUX_TRIM3` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 511 | `PWM_AUX_TRIM4` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 512 | `PWM_AUX_TRIM5` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 513 | `PWM_AUX_TRIM6` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 514 | `PWM_MAIN_DIS1` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 515 | `PWM_MAIN_DIS2` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 516 | `PWM_MAIN_DIS3` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 517 | `PWM_MAIN_DIS4` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 518 | `PWM_MAIN_DIS5` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 519 | `PWM_MAIN_DIS6` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 520 | `PWM_MAIN_DIS7` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 521 | `PWM_MAIN_DIS8` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 522 | `PWM_MAIN_DISARM` | Actuator output | 900 | 900 | 0 | same | metadata default |
| 523 | `PWM_MAIN_FAIL1` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 524 | `PWM_MAIN_FAIL2` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 525 | `PWM_MAIN_FAIL3` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 526 | `PWM_MAIN_FAIL4` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 527 | `PWM_MAIN_FAIL5` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 528 | `PWM_MAIN_FAIL6` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 529 | `PWM_MAIN_FAIL7` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 530 | `PWM_MAIN_FAIL8` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 531 | `PWM_MAIN_MAX` | Actuator output | 1950 | 1950 | 0 | same | rc.mc_defaults:17 set-default |
| 532 | `PWM_MAIN_MAX1` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 533 | `PWM_MAIN_MAX2` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 534 | `PWM_MAIN_MAX3` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 535 | `PWM_MAIN_MAX4` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 536 | `PWM_MAIN_MAX5` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 537 | `PWM_MAIN_MAX6` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 538 | `PWM_MAIN_MAX7` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 539 | `PWM_MAIN_MAX8` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 540 | `PWM_MAIN_MIN` | Actuator output | 1100 | 1075 | 25 | different | rc.mc_defaults:18 set-default |
| 541 | `PWM_MAIN_MIN1` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 542 | `PWM_MAIN_MIN2` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 543 | `PWM_MAIN_MIN3` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 544 | `PWM_MAIN_MIN4` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 545 | `PWM_MAIN_MIN5` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 546 | `PWM_MAIN_MIN6` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 547 | `PWM_MAIN_MIN7` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 548 | `PWM_MAIN_MIN8` | Actuator output | -1 | -1 | 0 | same | metadata default |
| 549 | `PWM_MAIN_OUT` | Actuator output | 1234 | 0 | 1234 | different | metadata default |
| 550 | `PWM_MAIN_RATE` | Actuator output | 400 | 400 | 0 | same | rc.mc_defaults:19 set-default |
| 551 | `PWM_MAIN_REV1` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 552 | `PWM_MAIN_REV2` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 553 | `PWM_MAIN_REV3` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 554 | `PWM_MAIN_REV4` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 555 | `PWM_MAIN_REV5` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 556 | `PWM_MAIN_REV6` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 557 | `PWM_MAIN_REV7` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 558 | `PWM_MAIN_REV8` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 559 | `PWM_MAIN_TRIM1` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 560 | `PWM_MAIN_TRIM2` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 561 | `PWM_MAIN_TRIM3` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 562 | `PWM_MAIN_TRIM4` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 563 | `PWM_MAIN_TRIM5` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 564 | `PWM_MAIN_TRIM6` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 565 | `PWM_MAIN_TRIM7` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 566 | `PWM_MAIN_TRIM8` | Actuator output | 0 | 0 | 0 | same | metadata default |
| 567 | `RC10_DZ` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 568 | `RC10_MAX` | RC/operator input | 2000 | 2000 | 0 | same | metadata default |
| 569 | `RC10_MIN` | RC/operator input | 1000 | 1000 | 0 | same | metadata default |
| 570 | `RC10_REV` | RC/operator input | 1 | 1 | 0 | same | metadata default |
| 571 | `RC10_TRIM` | RC/operator input | 1500 | 1500 | 0 | same | metadata default |
| 572 | `RC11_DZ` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 573 | `RC11_MAX` | RC/operator input | 2000 | 2000 | 0 | same | metadata default |
| 574 | `RC11_MIN` | RC/operator input | 1000 | 1000 | 0 | same | metadata default |
| 575 | `RC11_REV` | RC/operator input | 1 | 1 | 0 | same | metadata default |
| 576 | `RC11_TRIM` | RC/operator input | 1500 | 1500 | 0 | same | metadata default |
| 577 | `RC12_DZ` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 578 | `RC12_MAX` | RC/operator input | 2000 | 2000 | 0 | same | metadata default |
| 579 | `RC12_MIN` | RC/operator input | 1000 | 1000 | 0 | same | metadata default |
| 580 | `RC12_REV` | RC/operator input | 1 | 1 | 0 | same | metadata default |
| 581 | `RC12_TRIM` | RC/operator input | 1500 | 1500 | 0 | same | metadata default |
| 582 | `RC13_DZ` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 583 | `RC13_MAX` | RC/operator input | 2000 | 2000 | 0 | same | metadata default |
| 584 | `RC13_MIN` | RC/operator input | 1000 | 1000 | 0 | same | metadata default |
| 585 | `RC13_REV` | RC/operator input | 1 | 1 | 0 | same | metadata default |
| 586 | `RC13_TRIM` | RC/operator input | 1500 | 1500 | 0 | same | metadata default |
| 587 | `RC14_DZ` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 588 | `RC14_MAX` | RC/operator input | 2000 | 2000 | 0 | same | metadata default |
| 589 | `RC14_MIN` | RC/operator input | 1000 | 1000 | 0 | same | metadata default |
| 590 | `RC14_REV` | RC/operator input | 1 | 1 | 0 | same | metadata default |
| 591 | `RC14_TRIM` | RC/operator input | 1500 | 1500 | 0 | same | metadata default |
| 592 | `RC15_DZ` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 593 | `RC15_MAX` | RC/operator input | 2000 | 2000 | 0 | same | metadata default |
| 594 | `RC15_MIN` | RC/operator input | 1000 | 1000 | 0 | same | metadata default |
| 595 | `RC15_REV` | RC/operator input | 1 | 1 | 0 | same | metadata default |
| 596 | `RC15_TRIM` | RC/operator input | 1500 | 1500 | 0 | same | metadata default |
| 597 | `RC16_DZ` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 598 | `RC16_MAX` | RC/operator input | 2000 | 2000 | 0 | same | metadata default |
| 599 | `RC16_MIN` | RC/operator input | 1000 | 1000 | 0 | same | metadata default |
| 600 | `RC16_REV` | RC/operator input | 1 | 1 | 0 | same | metadata default |
| 601 | `RC16_TRIM` | RC/operator input | 1500 | 1500 | 0 | same | metadata default |
| 602 | `RC17_DZ` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 603 | `RC17_MAX` | RC/operator input | 2000 | 2000 | 0 | same | metadata default |
| 604 | `RC17_MIN` | RC/operator input | 1000 | 1000 | 0 | same | metadata default |
| 605 | `RC17_REV` | RC/operator input | 1 | 1 | 0 | same | metadata default |
| 606 | `RC17_TRIM` | RC/operator input | 1500 | 1500 | 0 | same | metadata default |
| 607 | `RC18_DZ` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 608 | `RC18_MAX` | RC/operator input | 2000 | 2000 | 0 | same | metadata default |
| 609 | `RC18_MIN` | RC/operator input | 1000 | 1000 | 0 | same | metadata default |
| 610 | `RC18_REV` | RC/operator input | 1 | 1 | 0 | same | metadata default |
| 611 | `RC18_TRIM` | RC/operator input | 1500 | 1500 | 0 | same | metadata default |
| 612 | `RC1_DZ` | RC/operator input | 10 | 10 | 0 | same | metadata default |
| 613 | `RC1_MAX` | RC/operator input | 1953 | 2000 | -47 | different | metadata default |
| 614 | `RC1_MIN` | RC/operator input | 1115 | 1000 | 115 | different | metadata default |
| 615 | `RC1_REV` | RC/operator input | 1 | 1 | 0 | same | metadata default |
| 616 | `RC1_TRIM` | RC/operator input | 1533 | 1500 | 33 | different | metadata default |
| 617 | `RC2_DZ` | RC/operator input | 10 | 10 | 0 | same | metadata default |
| 618 | `RC2_MAX` | RC/operator input | 1933 | 2000 | -67 | different | metadata default |
| 619 | `RC2_MIN` | RC/operator input | 1095 | 1000 | 95 | different | metadata default |
| 620 | `RC2_REV` | RC/operator input | -1 | 1 | -2 | different | metadata default |
| 621 | `RC2_TRIM` | RC/operator input | 1514 | 1500 | 14 | different | metadata default |
| 622 | `RC3_DZ` | RC/operator input | 10 | 10 | 0 | same | metadata default |
| 623 | `RC3_MAX` | RC/operator input | 1933 | 2000 | -67 | different | metadata default |
| 624 | `RC3_MIN` | RC/operator input | 1095 | 1000 | 95 | different | metadata default |
| 625 | `RC3_REV` | RC/operator input | 1 | 1 | 0 | same | metadata default |
| 626 | `RC3_TRIM` | RC/operator input | 1095 | 1500 | -405 | different | metadata default |
| 627 | `RC4_DZ` | RC/operator input | 10 | 10 | 0 | same | metadata default |
| 628 | `RC4_MAX` | RC/operator input | 1933 | 2000 | -67 | different | metadata default |
| 629 | `RC4_MIN` | RC/operator input | 1095 | 1000 | 95 | different | metadata default |
| 630 | `RC4_REV` | RC/operator input | 1 | 1 | 0 | same | metadata default |
| 631 | `RC4_TRIM` | RC/operator input | 1514 | 1500 | 14 | different | metadata default |
| 632 | `RC5_DZ` | RC/operator input | 10 | 10 | 0 | same | metadata default |
| 633 | `RC5_MAX` | RC/operator input | 2000 | 2000 | 0 | same | metadata default |
| 634 | `RC5_MIN` | RC/operator input | 1000 | 1000 | 0 | same | metadata default |
| 635 | `RC5_REV` | RC/operator input | 1 | 1 | 0 | same | metadata default |
| 636 | `RC5_TRIM` | RC/operator input | 1500 | 1500 | 0 | same | metadata default |
| 637 | `RC6_DZ` | RC/operator input | 10 | 10 | 0 | same | metadata default |
| 638 | `RC6_MAX` | RC/operator input | 2000 | 2000 | 0 | same | metadata default |
| 639 | `RC6_MIN` | RC/operator input | 1000 | 1000 | 0 | same | metadata default |
| 640 | `RC6_REV` | RC/operator input | 1 | 1 | 0 | same | metadata default |
| 641 | `RC6_TRIM` | RC/operator input | 1500 | 1500 | 0 | same | metadata default |
| 642 | `RC7_DZ` | RC/operator input | 10 | 10 | 0 | same | metadata default |
| 643 | `RC7_MAX` | RC/operator input | 2000 | 2000 | 0 | same | metadata default |
| 644 | `RC7_MIN` | RC/operator input | 1000 | 1000 | 0 | same | metadata default |
| 645 | `RC7_REV` | RC/operator input | 1 | 1 | 0 | same | metadata default |
| 646 | `RC7_TRIM` | RC/operator input | 1500 | 1500 | 0 | same | metadata default |
| 647 | `RC8_DZ` | RC/operator input | 10 | 10 | 0 | same | metadata default |
| 648 | `RC8_MAX` | RC/operator input | 2000 | 2000 | 0 | same | metadata default |
| 649 | `RC8_MIN` | RC/operator input | 1000 | 1000 | 0 | same | metadata default |
| 650 | `RC8_REV` | RC/operator input | 1 | 1 | 0 | same | metadata default |
| 651 | `RC8_TRIM` | RC/operator input | 1500 | 1500 | 0 | same | metadata default |
| 652 | `RC9_DZ` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 653 | `RC9_MAX` | RC/operator input | 2000 | 2000 | 0 | same | metadata default |
| 654 | `RC9_MIN` | RC/operator input | 1000 | 1000 | 0 | same | metadata default |
| 655 | `RC9_REV` | RC/operator input | 1 | 1 | 0 | same | metadata default |
| 656 | `RC9_TRIM` | RC/operator input | 1500 | 1500 | 0 | same | metadata default |
| 657 | `RC_ACRO_TH` | RC/operator input | 0.75 | 0.75 | 0 | same | metadata default |
| 658 | `RC_ARMSWITCH_TH` | RC/operator input | 0.75 | 0.75 | 0 | same | metadata default |
| 659 | `RC_ASSIST_TH` | RC/operator input | 0.25 | 0.25 | 0 | same | metadata default |
| 660 | `RC_AUTO_TH` | RC/operator input | 0.75 | 0.75 | 0 | same | metadata default |
| 661 | `RC_CHAN_CNT` | RC/operator input | 18 | 0 | 18 | different | metadata default |
| 662 | `RC_FAILS_THR` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 663 | `RC_GEAR_TH` | RC/operator input | 0.75 | 0.75 | 0 | same | metadata default |
| 664 | `RC_KILLSWITCH_TH` | RC/operator input | 0.75 | 0.75 | 0 | same | metadata default |
| 665 | `RC_LOITER_TH` | RC/operator input | 0.75 | 0.75 | 0 | same | metadata default |
| 666 | `RC_MAN_TH` | RC/operator input | 0.75 | 0.75 | 0 | same | metadata default |
| 667 | `RC_MAP_ACRO_SW` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 668 | `RC_MAP_ARM_SW` | RC/operator input | 5 | 0 | 5 | different | metadata default |
| 669 | `RC_MAP_AUX1` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 670 | `RC_MAP_AUX2` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 671 | `RC_MAP_AUX3` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 672 | `RC_MAP_AUX4` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 673 | `RC_MAP_AUX5` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 674 | `RC_MAP_AUX6` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 675 | `RC_MAP_FAILSAFE` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 676 | `RC_MAP_FLAPS` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 677 | `RC_MAP_FLTMODE` | RC/operator input | 7 | 0 | 7 | different | metadata default |
| 678 | `RC_MAP_GEAR_SW` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 679 | `RC_MAP_KILL_SW` | RC/operator input | 6 | 0 | 6 | different | metadata default |
| 680 | `RC_MAP_LOITER_SW` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 681 | `RC_MAP_MAN_SW` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 682 | `RC_MAP_MODE_SW` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 683 | `RC_MAP_OFFB_SW` | RC/operator input | 8 | 0 | 8 | different | metadata default |
| 684 | `RC_MAP_PARAM1` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 685 | `RC_MAP_PARAM2` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 686 | `RC_MAP_PARAM3` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 687 | `RC_MAP_PITCH` | RC/operator input | 2 | 0 | 2 | different | metadata default |
| 688 | `RC_MAP_POSCTL_SW` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 689 | `RC_MAP_RATT_SW` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 690 | `RC_MAP_RETURN_SW` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 691 | `RC_MAP_ROLL` | RC/operator input | 1 | 0 | 1 | different | metadata default |
| 692 | `RC_MAP_STAB_SW` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 693 | `RC_MAP_THROTTLE` | RC/operator input | 3 | 0 | 3 | different | metadata default |
| 694 | `RC_MAP_TRANS_SW` | RC/operator input | 7 | 0 | 7 | different | metadata default |
| 695 | `RC_MAP_YAW` | RC/operator input | 4 | 0 | 4 | different | metadata default |
| 696 | `RC_OFFB_TH` | RC/operator input | 0.75 | 0.75 | 0 | same | metadata default |
| 697 | `RC_POSCTL_TH` | RC/operator input | 0.75 | 0.75 | 0 | same | metadata default |
| 698 | `RC_RETURN_TH` | RC/operator input | 0.75 | 0.75 | 0 | same | metadata default |
| 699 | `RC_RSSI_PWM_CHAN` | RC/operator input | 0 | 0 | 0 | same | metadata default |
| 700 | `RC_RSSI_PWM_MAX` | RC/operator input | 2000 | 2000 | 0 | same | metadata default |
| 701 | `RC_RSSI_PWM_MIN` | RC/operator input | 1000 | 1000 | 0 | same | metadata default |
| 702 | `RC_STAB_TH` | RC/operator input | 0.5 | 0.5 | 0 | same | metadata default |
| 703 | `RC_TRANS_TH` | RC/operator input | 0.75 | 0.75 | 0 | same | metadata default |
| 704 | `RTL_CONE_ANG` | Return/landing | 45 | 45 | 0 | same | metadata default |
| 705 | `RTL_DESCEND_ALT` | Return/landing | 20 | 10 | 10 | different | rc.mc_defaults:15 set-default |
| 706 | `RTL_FLT_TIME` | Return/landing | 15 | 15 | 0 | same | metadata default |
| 707 | `RTL_LAND_DELAY` | Return/landing | 60 | 0 | 60 | different | metadata default |
| 708 | `RTL_LOITER_RAD` | Return/landing | 50 | 50 | 0 | same | metadata default |
| 709 | `RTL_MIN_DIST` | Return/landing | 10 | 10 | 0 | same | metadata default |
| 710 | `RTL_PLD_MD` | Return/landing | 0 | 0 | 0 | same | metadata default |
| 711 | `RTL_RETURN_ALT` | Return/landing | 20 | 30 | -10 | different | rc.mc_defaults:14 set-default |
| 712 | `RTL_TYPE` | Return/landing | 0 | 0 | 0 | same | metadata default |
| 713 | `SDLOG_BOOT_BAT` | Logging | 0 | 0 | 0 | same | metadata default |
| 714 | `SDLOG_DIRS_MAX` | Logging | 0 | 7 | -7 | different | rcS:155 set-default |
| 715 | `SDLOG_MISSION` | Logging | 0 | 0 | 0 | same | metadata default |
| 716 | `SDLOG_MODE` | Logging | 0 | 1 | -1 | different | rcS:152 set-default |
| 717 | `SDLOG_PROFILE` | Logging | 1023 | 131 | 892 | different | rcS:154 set-default |
| 718 | `SDLOG_UTC_OFFSET` | Logging | 0 | 0 | 0 | same | metadata default |
| 719 | `SDLOG_UUID` | Logging | 1 | 1 | 0 | same | metadata default |
| 720 | `SENS_BARO_QNH` | Sensor selection/offset | 1013.25 | 1013.25 | 0 | same | metadata default |
| 721 | `SENS_BARO_RATE` | Sensor selection/offset | 20 | 20 | 0 | same | metadata default |
| 722 | `SENS_BOARD_ROT` | Sensor selection/offset | 12 | 0 | 12 | different | metadata default |
| 723 | `SENS_BOARD_X_OFF` | Sensor selection/offset | 1.81090093 | 1e-06 | 1.81089993 | different | rcS simulated board offset |
| 724 | `SENS_BOARD_Y_OFF` | Sensor selection/offset | -0.249950871 | 0 | -0.249950871 | different | metadata default |
| 725 | `SENS_BOARD_Z_OFF` | Sensor selection/offset | 0 | 0 | 0 | same | metadata default |
| 726 | `SENS_CM8JL65_CFG` | Sensor selection/offset | 0 |  |  | missing_in_sim_metadata |  |
| 727 | `SENS_DPRES_OFF` | Sensor selection/offset | 0 | 0.001 | -0.001 | different | rcS simulated differential pressure offset |
| 728 | `SENS_EN_LL40LS` | Sensor selection/offset | 0 |  |  | missing_in_sim_metadata |  |
| 729 | `SENS_EN_MB12XX` | Sensor selection/offset | 0 |  |  | missing_in_sim_metadata |  |
| 730 | `SENS_EN_MPDT` | Sensor selection/offset | 0 |  |  | missing_in_sim_metadata |  |
| 731 | `SENS_EN_PAW3902` | Sensor selection/offset | 0 |  |  | missing_in_sim_metadata |  |
| 732 | `SENS_EN_PGA460` | Sensor selection/offset | 0 |  |  | missing_in_sim_metadata |  |
| 733 | `SENS_EN_PMW3901` | Sensor selection/offset | 0 |  |  | missing_in_sim_metadata |  |
| 734 | `SENS_EN_PX4FLOW` | Sensor selection/offset | 0 |  |  | missing_in_sim_metadata |  |
| 735 | `SENS_EN_SF1XX` | Sensor selection/offset | 0 |  |  | missing_in_sim_metadata |  |
| 736 | `SENS_EN_THERMAL` | Sensor selection/offset | -1 | -1 | 0 | same | metadata default |
| 737 | `SENS_EN_TRANGER` | Sensor selection/offset | 0 |  |  | missing_in_sim_metadata |  |
| 738 | `SENS_EN_VL53L1X` | Sensor selection/offset | 0 |  |  | missing_in_sim_metadata |  |
| 739 | `SENS_EXT_I2C_PRB` | Sensor selection/offset | 1 | 1 | 0 | same | metadata default |
| 740 | `SENS_FLOW_MAXHGT` | Sensor selection/offset | 3 | 3 | 0 | same | metadata default |
| 741 | `SENS_FLOW_MAXR` | Sensor selection/offset | 2.5 | 2.5 | 0 | same | metadata default |
| 742 | `SENS_FLOW_MINHGT` | Sensor selection/offset | 0.699999988 | 0.7 | -1.19209289e-08 | same | metadata default |
| 743 | `SENS_FLOW_ROT` | Sensor selection/offset | 0 | 6 | -6 | different | metadata default |
| 744 | `SENS_GPS_MASK` | Sensor selection/offset | 0 | 0 | 0 | same | metadata default |
| 745 | `SENS_GPS_PRIME` | Sensor selection/offset | 0 | 0 | 0 | same | metadata default |
| 746 | `SENS_GPS_TAU` | Sensor selection/offset | 10 | 10 | 0 | same | metadata default |
| 747 | `SENS_IMU_MODE` | Sensor selection/offset | 0 | 0 | 0 | same | rcS:145 set-default |
| 748 | `SENS_LEDDAR1_CFG` | Sensor selection/offset | 0 |  |  | missing_in_sim_metadata |  |
| 749 | `SENS_MAG_MODE` | Sensor selection/offset | 1 | 0 | 1 | different | rcS:147 set-default |
| 750 | `SENS_MAG_RATE` | Sensor selection/offset | 50 | 50 | 0 | same | metadata default |
| 751 | `SENS_SF0X_CFG` | Sensor selection/offset | 0 |  |  | missing_in_sim_metadata |  |
| 752 | `SENS_TFLOW_CFG` | Sensor selection/offset | 0 |  |  | missing_in_sim_metadata |  |
| 753 | `SENS_TFMINI_CFG` | Sensor selection/offset | 0 |  |  | missing_in_sim_metadata |  |
| 754 | `SENS_ULAND_CFG` | Sensor selection/offset | 0 |  |  | missing_in_sim_metadata |  |
| 755 | `SENS_UWB_CFG` | Sensor selection/offset | 201 |  |  | missing_in_sim_metadata |  |
| 756 | `SENS_ZYFLOW_CFG` | Sensor selection/offset | 0 |  |  | missing_in_sim_metadata |  |
| 757 | `SER_TEL1_BAUD` | Serial port | 921600 |  |  | missing_in_sim_metadata |  |
| 758 | `SER_TEL2_BAUD` | Serial port | 115200 |  |  | missing_in_sim_metadata |  |
| 759 | `SYS_AUTOCONFIG` | System/autostart | 0 | 0 | 0 | same | rcS final SYS_AUTOCONFIG after first autoconfig |
| 760 | `SYS_AUTOSTART` | System/autostart | 4011 | 10016 | -6005 | different | rcS set SYS_AUTOSTART for PX4_SIM_MODEL=iris |
| 761 | `SYS_BL_UPDATE` | System/autostart | 0 | 0 | 0 | same | metadata default |
| 762 | `SYS_CAL_ACCEL` | System/autostart | 0 | 0 | 0 | same | metadata default |
| 763 | `SYS_CAL_BARO` | System/autostart | 0 | 0 | 0 | same | metadata default |
| 764 | `SYS_CAL_GYRO` | System/autostart | 0 | 0 | 0 | same | metadata default |
| 765 | `SYS_CAL_TDEL` | System/autostart | 24 | 24 | 0 | same | metadata default |
| 766 | `SYS_CAL_TMAX` | System/autostart | 10 | 10 | 0 | same | metadata default |
| 767 | `SYS_CAL_TMIN` | System/autostart | 5 | 5 | 0 | same | metadata default |
| 768 | `SYS_FAC_CAL_MODE` | System/autostart | 0 | 0 | 0 | same | metadata default |
| 769 | `SYS_FAILURE_EN` | System/autostart | 0 | 0 | 0 | same | metadata default |
| 770 | `SYS_HAS_BARO` | System/autostart | 1 | 1 | 0 | same | metadata default |
| 771 | `SYS_HAS_GPS` | System/autostart | 1 | 1 | 0 | same | metadata default |
| 772 | `SYS_HAS_MAG` | System/autostart | 1 | 1 | 0 | same | metadata default |
| 773 | `SYS_HITL` | System/autostart | 0 | 0 | 0 | same | metadata default |
| 774 | `SYS_MC_EST_GROUP` | System/autostart | 2 | 2 | 0 | same | metadata default |
| 775 | `SYS_RESTART_TYPE` | System/autostart | 2 | 2 | 0 | same | rcS simulated restart type |
| 776 | `SYS_STCK_EN` | System/autostart | 1 | 1 | 0 | same | metadata default |
| 777 | `SYS_VEHICLE_RESP` | System/autostart | -0.400000006 | -0.4 | -5.96046446e-09 | same | metadata default |
| 778 | `SYS_ZY_CTRL_EN` | System/autostart | 1 |  |  | missing_in_sim_metadata |  |
| 779 | `SYS_ZY_UART_EN` | System/autostart | 0 |  |  | missing_in_sim_metadata |  |
| 780 | `TC_A_ENABLE` | Other | 0 | 0 | 0 | same | metadata default |
| 781 | `TC_B_ENABLE` | Other | 0 | 0 | 0 | same | metadata default |
| 782 | `TC_G_ENABLE` | Other | 0 | 0 | 0 | same | metadata default |
| 783 | `TEL_BST_EN` | Telemetry | 0 |  |  | missing_in_sim_metadata |  |
| 784 | `TEL_FRSKY_CONFIG` | Telemetry | 0 |  |  | missing_in_sim_metadata |  |
| 785 | `TEL_HOTT_CONFIG` | Telemetry | 0 |  |  | missing_in_sim_metadata |  |
| 786 | `THR_MDL_FAC` | Other | 0 | 0 | 0 | same | metadata default |
| 787 | `TRIG_MODE` | Trigger/camera | 0 | 0 | 0 | same | metadata default |
| 788 | `UAVCAN_BAT_MON` | UAVCAN | 0 |  |  | missing_in_sim_metadata |  |
| 789 | `UAVCAN_BITRATE` | UAVCAN | 1000000 |  |  | missing_in_sim_metadata |  |
| 790 | `UAVCAN_ENABLE` | UAVCAN | 2 |  |  | missing_in_sim_metadata |  |
| 791 | `UAVCAN_ESC_IDLT` | UAVCAN | 1 |  |  | missing_in_sim_metadata |  |
| 792 | `UAVCAN_LGT_ANTCL` | UAVCAN | 2 |  |  | missing_in_sim_metadata |  |
| 793 | `UAVCAN_LGT_LAND` | UAVCAN | 0 |  |  | missing_in_sim_metadata |  |
| 794 | `UAVCAN_LGT_NAV` | UAVCAN | 3 |  |  | missing_in_sim_metadata |  |
| 795 | `UAVCAN_LGT_STROB` | UAVCAN | 1 |  |  | missing_in_sim_metadata |  |
| 796 | `UAVCAN_NODE_ID` | UAVCAN | 1 |  |  | missing_in_sim_metadata |  |
| 797 | `UAVCAN_RNG_MAX` | UAVCAN | 200 |  |  | missing_in_sim_metadata |  |
| 798 | `UAVCAN_RNG_MIN` | UAVCAN | 0.300000012 |  |  | missing_in_sim_metadata |  |
| 799 | `VT_B_DEC_MSS` | VTOL | 2 | 2 | 0 | same | metadata default |
| 800 | `VT_B_REV_DEL` | VTOL | 0 | 0 | 0 | same | metadata default |
| 801 | `WV_EN` | Other | 0 | 0 | 0 | same | metadata default |

## SITL Parameters Not Exported By FS150

These exist in the v1.12.3 SITL metadata/effective baseline but do not appear in the FS150 exported parameter file. The complete machine-readable list is in the CSV next to this report.

| # | Parameter | Family | SITL iris default | SITL source |
| ---: | --- | --- | ---: | --- |
| 1 | `ASPD_BETA_GATE` | Other | 1 | metadata default |
| 2 | `ASPD_BETA_NOISE` | Other | 0.3 | metadata default |
| 3 | `ASPD_DO_CHECKS` | Other | 1 | metadata default |
| 4 | `ASPD_FALLBACK_GW` | Other | 0 | metadata default |
| 5 | `ASPD_FS_INNOV` | Other | 1 | metadata default |
| 6 | `ASPD_FS_INTEG` | Other | 5 | metadata default |
| 7 | `ASPD_FS_T_START` | Other | -1 | metadata default |
| 8 | `ASPD_FS_T_STOP` | Other | 2 | metadata default |
| 9 | `ASPD_PRIMARY` | Other | 1 | metadata default |
| 10 | `ASPD_SCALE_EST` | Other | 0 | metadata default |
| 11 | `ASPD_SC_P_NOISE` | Other | 0.0001 | metadata default |
| 12 | `ASPD_TAS_GATE` | Other | 3 | metadata default |
| 13 | `ASPD_TAS_NOISE` | Other | 1.4 | metadata default |
| 14 | `ASPD_W_P_NOISE` | Other | 0.1 | metadata default |
| 15 | `ATT_ACC_COMP` | Other | 1 | metadata default |
| 16 | `ATT_BIAS_MAX` | Other | 0.05 | metadata default |
| 17 | `ATT_EXT_HDG_M` | Other | 0 | metadata default |
| 18 | `ATT_MAG_DECL` | Other | 0 | metadata default |
| 19 | `ATT_MAG_DECL_A` | Other | 1 | metadata default |
| 20 | `ATT_W_ACC` | Other | 0.2 | metadata default |
| 21 | `ATT_W_EXT_HDG` | Other | 0.1 | metadata default |
| 22 | `ATT_W_GYRO_BIAS` | Other | 0.1 | metadata default |
| 23 | `ATT_W_MAG` | Other | 0.1 | metadata default |
| 24 | `BAT2_CAPACITY` | Battery/power | -1 | metadata default |
| 25 | `BAT2_N_CELLS` | Battery/power | 0 | metadata default |
| 26 | `BAT2_R_INTERNAL` | Battery/power | -1 | metadata default |
| 27 | `BAT2_SOURCE` | Battery/power | -1 | metadata default |
| 28 | `BAT2_V_CHARGED` | Battery/power | 4.05 | metadata default |
| 29 | `BAT2_V_EMPTY` | Battery/power | 3.5 | metadata default |
| 30 | `BAT2_V_LOAD_DROP` | Battery/power | 0.3 | metadata default |
| 31 | `CAL_ACC2_PRIO` | Sensor calibration | -1 | metadata default |
| 32 | `CAL_ACC2_ROT` | Sensor calibration | -1 | metadata default |
| 33 | `CAL_ACC2_XOFF` | Sensor calibration | 0 | metadata default |
| 34 | `CAL_ACC2_XSCALE` | Sensor calibration | 1 | metadata default |
| 35 | `CAL_ACC2_YOFF` | Sensor calibration | 0 | metadata default |
| 36 | `CAL_ACC2_YSCALE` | Sensor calibration | 1 | metadata default |
| 37 | `CAL_ACC2_ZOFF` | Sensor calibration | 0 | metadata default |
| 38 | `CAL_ACC2_ZSCALE` | Sensor calibration | 1 | metadata default |
| 39 | `CAL_ACC3_PRIO` | Sensor calibration | -1 | metadata default |
| 40 | `CAL_ACC3_ROT` | Sensor calibration | -1 | metadata default |
| 41 | `CAL_ACC3_XOFF` | Sensor calibration | 0 | metadata default |
| 42 | `CAL_ACC3_XSCALE` | Sensor calibration | 1 | metadata default |
| 43 | `CAL_ACC3_YOFF` | Sensor calibration | 0 | metadata default |
| 44 | `CAL_ACC3_YSCALE` | Sensor calibration | 1 | metadata default |
| 45 | `CAL_ACC3_ZOFF` | Sensor calibration | 0 | metadata default |
| 46 | `CAL_ACC3_ZSCALE` | Sensor calibration | 1 | metadata default |
| 47 | `CAL_GYRO2_PRIO` | Sensor calibration | -1 | metadata default |
| 48 | `CAL_GYRO2_ROT` | Sensor calibration | -1 | metadata default |
| 49 | `CAL_GYRO2_XOFF` | Sensor calibration | 0 | metadata default |
| 50 | `CAL_GYRO2_YOFF` | Sensor calibration | 0 | metadata default |
| 51 | `CAL_GYRO2_ZOFF` | Sensor calibration | 0 | metadata default |
| 52 | `CAL_GYRO3_PRIO` | Sensor calibration | -1 | metadata default |
| 53 | `CAL_GYRO3_ROT` | Sensor calibration | -1 | metadata default |
| 54 | `CAL_GYRO3_XOFF` | Sensor calibration | 0 | metadata default |
| 55 | `CAL_GYRO3_YOFF` | Sensor calibration | 0 | metadata default |
| 56 | `CAL_GYRO3_ZOFF` | Sensor calibration | 0 | metadata default |
| 57 | `CAL_MAG1_PRIO` | Sensor calibration | -1 | metadata default |
| 58 | `CAL_MAG1_XCOMP` | Sensor calibration | 0 | metadata default |
| 59 | `CAL_MAG1_XODIAG` | Sensor calibration | 0 | metadata default |
| 60 | `CAL_MAG1_XOFF` | Sensor calibration | 0 | metadata default |
| 61 | `CAL_MAG1_XSCALE` | Sensor calibration | 1 | metadata default |
| 62 | `CAL_MAG1_YCOMP` | Sensor calibration | 0 | metadata default |
| 63 | `CAL_MAG1_YODIAG` | Sensor calibration | 0 | metadata default |
| 64 | `CAL_MAG1_YOFF` | Sensor calibration | 0 | metadata default |
| 65 | `CAL_MAG1_YSCALE` | Sensor calibration | 1 | metadata default |
| 66 | `CAL_MAG1_ZCOMP` | Sensor calibration | 0 | metadata default |
| 67 | `CAL_MAG1_ZODIAG` | Sensor calibration | 0 | metadata default |
| 68 | `CAL_MAG1_ZOFF` | Sensor calibration | 0 | metadata default |
| 69 | `CAL_MAG1_ZSCALE` | Sensor calibration | 1 | metadata default |
| 70 | `CAL_MAG2_PRIO` | Sensor calibration | -1 | metadata default |
| 71 | `CAL_MAG2_XCOMP` | Sensor calibration | 0 | metadata default |
| 72 | `CAL_MAG2_XODIAG` | Sensor calibration | 0 | metadata default |
| 73 | `CAL_MAG2_XOFF` | Sensor calibration | 0 | metadata default |
| 74 | `CAL_MAG2_XSCALE` | Sensor calibration | 1 | metadata default |
| 75 | `CAL_MAG2_YCOMP` | Sensor calibration | 0 | metadata default |
| 76 | `CAL_MAG2_YODIAG` | Sensor calibration | 0 | metadata default |
| 77 | `CAL_MAG2_YOFF` | Sensor calibration | 0 | metadata default |
| 78 | `CAL_MAG2_YSCALE` | Sensor calibration | 1 | metadata default |
| 79 | `CAL_MAG2_ZCOMP` | Sensor calibration | 0 | metadata default |
| 80 | `CAL_MAG2_ZODIAG` | Sensor calibration | 0 | metadata default |
| 81 | `CAL_MAG2_ZOFF` | Sensor calibration | 0 | metadata default |
| 82 | `CAL_MAG2_ZSCALE` | Sensor calibration | 1 | metadata default |
| 83 | `CAL_MAG3_PRIO` | Sensor calibration | -1 | metadata default |
| 84 | `CAL_MAG3_XCOMP` | Sensor calibration | 0 | metadata default |
| 85 | `CAL_MAG3_XODIAG` | Sensor calibration | 0 | metadata default |
| 86 | `CAL_MAG3_XOFF` | Sensor calibration | 0 | metadata default |
| 87 | `CAL_MAG3_XSCALE` | Sensor calibration | 1 | metadata default |
| 88 | `CAL_MAG3_YCOMP` | Sensor calibration | 0 | metadata default |
| 89 | `CAL_MAG3_YODIAG` | Sensor calibration | 0 | metadata default |
| 90 | `CAL_MAG3_YOFF` | Sensor calibration | 0 | metadata default |
| 91 | `CAL_MAG3_YSCALE` | Sensor calibration | 1 | metadata default |
| 92 | `CAL_MAG3_ZCOMP` | Sensor calibration | 0 | metadata default |
| 93 | `CAL_MAG3_ZODIAG` | Sensor calibration | 0 | metadata default |
| 94 | `CAL_MAG3_ZOFF` | Sensor calibration | 0 | metadata default |
| 95 | `CAL_MAG3_ZSCALE` | Sensor calibration | 1 | metadata default |
| 96 | `CAM_CAP_DELAY` | Other | 0 | metadata default |
| 97 | `CAM_CAP_EDGE` | Other | 0 | metadata default |
| 98 | `CAM_CAP_MODE` | Other | 0 | metadata default |
| 99 | `CBRK_IO_SAFETY` | Safety circuit breaker | 22027 | metadata default |
| 100 | `COM_ARM_ARSP_EN` | Commander/failsafe | 1 | metadata default |
| 101 | `EKF2_MULTI_MAG` | Estimator | 2 | rcS:146 set-default |
| 102 | `EXFW_HDNG_P` | Other | 0.1 | metadata default |
| 103 | `EXFW_PITCH_P` | Other | 0.2 | metadata default |
| 104 | `EXFW_ROLL_P` | Other | 0.2 | metadata default |
| 105 | `FW_ACRO_X_MAX` | Fixed-wing | 90 | metadata default |
| 106 | `FW_ACRO_Y_MAX` | Fixed-wing | 90 | metadata default |
| 107 | `FW_ACRO_Z_MAX` | Fixed-wing | 45 | metadata default |
| 108 | `FW_AIRSPD_MAX` | Fixed-wing | 20 | metadata default |
| 109 | `FW_AIRSPD_MIN` | Fixed-wing | 10 | metadata default |
| 110 | `FW_AIRSPD_STALL` | Fixed-wing | 7 | metadata default |
| 111 | `FW_AIRSPD_TRIM` | Fixed-wing | 15 | metadata default |
| 112 | `FW_ARSP_MODE` | Fixed-wing | 0 | metadata default |
| 113 | `FW_ARSP_SCALE_EN` | Fixed-wing | 1 | metadata default |
| 114 | `FW_BAT_SCALE_EN` | Fixed-wing | 0 | metadata default |
| 115 | `FW_CLMBOUT_DIFF` | Fixed-wing | 10 | metadata default |
| 116 | `FW_DTRIM_P_FLPS` | Fixed-wing | 0 | metadata default |
| 117 | `FW_DTRIM_P_VMAX` | Fixed-wing | 0 | metadata default |
| 118 | `FW_DTRIM_P_VMIN` | Fixed-wing | 0 | metadata default |
| 119 | `FW_DTRIM_R_FLPS` | Fixed-wing | 0 | metadata default |
| 120 | `FW_DTRIM_R_VMAX` | Fixed-wing | 0 | metadata default |
| 121 | `FW_DTRIM_R_VMIN` | Fixed-wing | 0 | metadata default |
| 122 | `FW_DTRIM_Y_VMAX` | Fixed-wing | 0 | metadata default |
| 123 | `FW_DTRIM_Y_VMIN` | Fixed-wing | 0 | metadata default |
| 124 | `FW_FLAPERON_SCL` | Fixed-wing | 0 | metadata default |
| 125 | `FW_FLAPS_LND_SCL` | Fixed-wing | 1 | metadata default |
| 126 | `FW_FLAPS_SCL` | Fixed-wing | 1 | metadata default |
| 127 | `FW_FLAPS_TO_SCL` | Fixed-wing | 0 | metadata default |
| 128 | `FW_GND_SPD_MIN` | Fixed-wing | 5 | metadata default |
| 129 | `FW_L1_DAMPING` | Fixed-wing | 0.75 | metadata default |
| 130 | `FW_L1_PERIOD` | Fixed-wing | 20 | metadata default |
| 131 | `FW_L1_R_SLEW_MAX` | Fixed-wing | 90 | metadata default |
| 132 | `FW_LND_AIRSPD_SC` | Fixed-wing | 1.3 | metadata default |
| 133 | `FW_LND_ANG` | Fixed-wing | 5 | metadata default |
| 134 | `FW_LND_EARLYCFG` | Fixed-wing | 0 | metadata default |
| 135 | `FW_LND_FLALT` | Fixed-wing | 3 | metadata default |
| 136 | `FW_LND_FL_PMAX` | Fixed-wing | 15 | metadata default |
| 137 | `FW_LND_FL_PMIN` | Fixed-wing | 2.5 | metadata default |
| 138 | `FW_LND_HHDIST` | Fixed-wing | 15 | metadata default |
| 139 | `FW_LND_HVIRT` | Fixed-wing | 10 | metadata default |
| 140 | `FW_LND_THRTC_SC` | Fixed-wing | 1 | metadata default |
| 141 | `FW_LND_TLALT` | Fixed-wing | -1 | metadata default |
| 142 | `FW_LND_USETER` | Fixed-wing | 0 | metadata default |
| 143 | `FW_MAN_P_MAX` | Fixed-wing | 45 | metadata default |
| 144 | `FW_MAN_P_SC` | Fixed-wing | 1 | metadata default |
| 145 | `FW_MAN_R_MAX` | Fixed-wing | 45 | metadata default |
| 146 | `FW_MAN_R_SC` | Fixed-wing | 1 | metadata default |
| 147 | `FW_MAN_Y_SC` | Fixed-wing | 1 | metadata default |
| 148 | `FW_POSCTL_INV_ST` | Fixed-wing | 0 | metadata default |
| 149 | `FW_PR_FF` | Fixed-wing | 0.5 | metadata default |
| 150 | `FW_PR_I` | Fixed-wing | 0.1 | metadata default |
| 151 | `FW_PR_IMAX` | Fixed-wing | 0.4 | metadata default |
| 152 | `FW_PR_P` | Fixed-wing | 0.08 | metadata default |
| 153 | `FW_PSP_OFF` | Fixed-wing | 0 | metadata default |
| 154 | `FW_P_LIM_MAX` | Fixed-wing | 45 | metadata default |
| 155 | `FW_P_LIM_MIN` | Fixed-wing | -45 | metadata default |
| 156 | `FW_P_RMAX_NEG` | Fixed-wing | 60 | metadata default |
| 157 | `FW_P_RMAX_POS` | Fixed-wing | 60 | metadata default |
| 158 | `FW_P_TC` | Fixed-wing | 0.4 | metadata default |
| 159 | `FW_RLL_TO_YAW_FF` | Fixed-wing | 0 | metadata default |
| 160 | `FW_RR_FF` | Fixed-wing | 0.5 | metadata default |
| 161 | `FW_RR_I` | Fixed-wing | 0.1 | metadata default |
| 162 | `FW_RR_IMAX` | Fixed-wing | 0.2 | metadata default |
| 163 | `FW_RR_P` | Fixed-wing | 0.05 | metadata default |
| 164 | `FW_R_LIM` | Fixed-wing | 50 | metadata default |
| 165 | `FW_R_RMAX` | Fixed-wing | 70 | metadata default |
| 166 | `FW_R_TC` | Fixed-wing | 0.4 | metadata default |
| 167 | `FW_THR_ALT_SCL` | Fixed-wing | 0 | metadata default |
| 168 | `FW_THR_CRUISE` | Fixed-wing | 0.6 | metadata default |
| 169 | `FW_THR_IDLE` | Fixed-wing | 0.15 | metadata default |
| 170 | `FW_THR_LND_MAX` | Fixed-wing | 1 | metadata default |
| 171 | `FW_THR_MAX` | Fixed-wing | 1 | metadata default |
| 172 | `FW_THR_MIN` | Fixed-wing | 0 | metadata default |
| 173 | `FW_THR_SLEW_MAX` | Fixed-wing | 0 | metadata default |
| 174 | `FW_TKO_PITCH_MIN` | Fixed-wing | 10 | metadata default |
| 175 | `FW_T_ALT_TC` | Fixed-wing | 5 | metadata default |
| 176 | `FW_T_CLMB_MAX` | Fixed-wing | 5 | metadata default |
| 177 | `FW_T_CLMB_R_SP` | Fixed-wing | 3 | metadata default |
| 178 | `FW_T_HRATE_FF` | Fixed-wing | 0.3 | metadata default |
| 179 | `FW_T_I_GAIN_PIT` | Fixed-wing | 0.1 | metadata default |
| 180 | `FW_T_I_GAIN_THR` | Fixed-wing | 0.3 | metadata default |
| 181 | `FW_T_PTCH_DAMP` | Fixed-wing | 0.1 | metadata default |
| 182 | `FW_T_RLL2THR` | Fixed-wing | 15 | metadata default |
| 183 | `FW_T_SEB_R_FF` | Fixed-wing | 1 | metadata default |
| 184 | `FW_T_SINK_MAX` | Fixed-wing | 5 | metadata default |
| 185 | `FW_T_SINK_MIN` | Fixed-wing | 2 | metadata default |
| 186 | `FW_T_SINK_R_SP` | Fixed-wing | 2 | metadata default |
| 187 | `FW_T_SPDWEIGHT` | Fixed-wing | 1 | metadata default |
| 188 | `FW_T_SPD_OMEGA` | Fixed-wing | 2 | metadata default |
| 189 | `FW_T_STE_R_TC` | Fixed-wing | 0.4 | metadata default |
| 190 | `FW_T_TAS_R_TC` | Fixed-wing | 0.2 | metadata default |
| 191 | `FW_T_TAS_TC` | Fixed-wing | 5 | metadata default |
| 192 | `FW_T_THR_DAMP` | Fixed-wing | 0.1 | metadata default |
| 193 | `FW_T_VERT_ACC` | Fixed-wing | 7 | metadata default |
| 194 | `FW_WR_FF` | Fixed-wing | 0.2 | metadata default |
| 195 | `FW_WR_I` | Fixed-wing | 0.1 | metadata default |
| 196 | `FW_WR_IMAX` | Fixed-wing | 1 | metadata default |
| 197 | `FW_WR_P` | Fixed-wing | 0.5 | metadata default |
| 198 | `FW_W_EN` | Fixed-wing | 0 | metadata default |
| 199 | `FW_W_RMAX` | Fixed-wing | 30 | metadata default |
| 200 | `FW_YR_FF` | Fixed-wing | 0.3 | metadata default |
| 201 | `FW_YR_I` | Fixed-wing | 0.1 | metadata default |
| 202 | `FW_YR_IMAX` | Fixed-wing | 0.2 | metadata default |
| 203 | `FW_YR_P` | Fixed-wing | 0.05 | metadata default |
| 204 | `FW_Y_RMAX` | Fixed-wing | 50 | metadata default |
| 205 | `GND_L1_DAMPING` | Other | 0.75 | metadata default |
| 206 | `GND_L1_DIST` | Other | 1 | metadata default |
| 207 | `GND_L1_PERIOD` | Other | 5 | metadata default |
| 208 | `GND_MAN_Y_MAX` | Other | 150 | metadata default |
| 209 | `GND_MAX_ANG` | Other | 0.7854 | metadata default |
| 210 | `GND_SPEED_D` | Other | 0.001 | metadata default |
| 211 | `GND_SPEED_I` | Other | 3 | metadata default |
| 212 | `GND_SPEED_IMAX` | Other | 1 | metadata default |
| 213 | `GND_SPEED_MAX` | Other | 10 | metadata default |
| 214 | `GND_SPEED_P` | Other | 2 | metadata default |
| 215 | `GND_SPEED_THR_SC` | Other | 1 | metadata default |
| 216 | `GND_SPEED_TRIM` | Other | 3 | metadata default |
| 217 | `GND_SP_CTRL_MODE` | Other | 1 | metadata default |
| 218 | `GND_THR_CRUISE` | Other | 0.1 | metadata default |
| 219 | `GND_THR_MAX` | Other | 0.3 | metadata default |
| 220 | `GND_THR_MIN` | Other | 0 | metadata default |
| 221 | `GND_WHEEL_BASE` | Other | 0.31 | metadata default |
| 222 | `GPS_1_GNSS` | GPS | 0 | metadata default |
| 223 | `GPS_1_PROTOCOL` | GPS | 1 | metadata default |
| 224 | `GPS_2_GNSS` | GPS | 0 | metadata default |
| 225 | `GPS_2_PROTOCOL` | GPS | 1 | metadata default |
| 226 | `GPS_UBX_DYNMODEL` | GPS | 6 | rc.mc_defaults:21 set-default |
| 227 | `GPS_UBX_MODE` | GPS | 0 | metadata default |
| 228 | `LAUN_ALL_ON` | Other | 0 | metadata default |
| 229 | `LAUN_CAT_A` | Other | 30 | metadata default |
| 230 | `LAUN_CAT_MDEL` | Other | 0 | metadata default |
| 231 | `LAUN_CAT_PMAX` | Other | 30 | metadata default |
| 232 | `LAUN_CAT_T` | Other | 0.05 | metadata default |
| 233 | `LNDFW_AIRSPD_MAX` | Other | 6 | metadata default |
| 234 | `LNDFW_VEL_XY_MAX` | Other | 5 | metadata default |
| 235 | `LNDFW_VEL_Z_MAX` | Other | 3 | metadata default |
| 236 | `LNDFW_XYACC_MAX` | Other | 8 | metadata default |
| 237 | `LPE_ACC_XY` | Estimator | 0.012 | metadata default |
| 238 | `LPE_ACC_Z` | Estimator | 0.02 | metadata default |
| 239 | `LPE_BAR_Z` | Estimator | 3 | metadata default |
| 240 | `LPE_EPH_MAX` | Estimator | 3 | metadata default |
| 241 | `LPE_EPV_MAX` | Estimator | 5 | metadata default |
| 242 | `LPE_FAKE_ORIGIN` | Estimator | 0 | metadata default |
| 243 | `LPE_FGYRO_HP` | Estimator | 0.001 | metadata default |
| 244 | `LPE_FLW_OFF_Z` | Estimator | 0 | metadata default |
| 245 | `LPE_FLW_QMIN` | Estimator | 150 | metadata default |
| 246 | `LPE_FLW_R` | Estimator | 7 | metadata default |
| 247 | `LPE_FLW_RR` | Estimator | 7 | metadata default |
| 248 | `LPE_FLW_SCALE` | Estimator | 1.3 | metadata default |
| 249 | `LPE_FUSION` | Estimator | 145 | metadata default |
| 250 | `LPE_GPS_DELAY` | Estimator | 0.29 | metadata default |
| 251 | `LPE_GPS_VXY` | Estimator | 0.25 | metadata default |
| 252 | `LPE_GPS_VZ` | Estimator | 0.25 | metadata default |
| 253 | `LPE_GPS_XY` | Estimator | 1 | metadata default |
| 254 | `LPE_GPS_Z` | Estimator | 3 | metadata default |
| 255 | `LPE_LAND_VXY` | Estimator | 0.05 | metadata default |
| 256 | `LPE_LAND_Z` | Estimator | 0.03 | metadata default |
| 257 | `LPE_LAT` | Estimator | 47.397742 | metadata default |
| 258 | `LPE_LDR_OFF_Z` | Estimator | 0 | metadata default |
| 259 | `LPE_LDR_Z` | Estimator | 0.03 | metadata default |
| 260 | `LPE_LON` | Estimator | 8.545594 | metadata default |
| 261 | `LPE_LT_COV` | Estimator | 0.0001 | metadata default |
| 262 | `LPE_PN_B` | Estimator | 0.001 | metadata default |
| 263 | `LPE_PN_P` | Estimator | 0.1 | metadata default |
| 264 | `LPE_PN_T` | Estimator | 0.001 | metadata default |
| 265 | `LPE_PN_V` | Estimator | 0.1 | metadata default |
| 266 | `LPE_SNR_OFF_Z` | Estimator | 0 | metadata default |
| 267 | `LPE_SNR_Z` | Estimator | 0.05 | metadata default |
| 268 | `LPE_T_MAX_GRADE` | Estimator | 1 | metadata default |
| 269 | `LPE_VIC_P` | Estimator | 0.001 | metadata default |
| 270 | `LPE_VIS_DELAY` | Estimator | 0.1 | metadata default |
| 271 | `LPE_VIS_XY` | Estimator | 0.1 | metadata default |
| 272 | `LPE_VIS_Z` | Estimator | 0.5 | metadata default |
| 273 | `LPE_VXY_PUB` | Estimator | 0.3 | metadata default |
| 274 | `LPE_X_LP` | Estimator | 5 | metadata default |
| 275 | `LPE_Z_PUB` | Estimator | 1 | metadata default |
| 276 | `LTEST_ACC_UNC` | Other | 10 | metadata default |
| 277 | `LTEST_MEAS_UNC` | Other | 0.005 | metadata default |
| 278 | `LTEST_MODE` | Other | 0 | metadata default |
| 279 | `LTEST_POS_UNC_IN` | Other | 0.1 | metadata default |
| 280 | `LTEST_SCALE_X` | Other | 1 | metadata default |
| 281 | `LTEST_SCALE_Y` | Other | 1 | metadata default |
| 282 | `LTEST_VEL_UNC_IN` | Other | 0.1 | metadata default |
| 283 | `MAV_0_BROADCAST` | MAVLink/system identity | 1 | metadata default |
| 284 | `MAV_0_REMOTE_PRT` | MAVLink/system identity | 14550 | metadata default |
| 285 | `MAV_0_UDP_PRT` | MAVLink/system identity | 14556 | metadata default |
| 286 | `MAV_1_BROADCAST` | MAVLink/system identity | 0 | metadata default |
| 287 | `MAV_1_REMOTE_PRT` | MAVLink/system identity | 0 | metadata default |
| 288 | `MAV_1_UDP_PRT` | MAVLink/system identity | 0 | metadata default |
| 289 | `MAV_2_BROADCAST` | MAVLink/system identity | 0 | metadata default |
| 290 | `MAV_2_FORWARD` | MAVLink/system identity | 0 | metadata default |
| 291 | `MAV_2_MODE` | MAVLink/system identity | 0 | metadata default |
| 292 | `MAV_2_RADIO_CTL` | MAVLink/system identity | 1 | metadata default |
| 293 | `MAV_2_RATE` | MAVLink/system identity | 0 | metadata default |
| 294 | `MAV_2_REMOTE_PRT` | MAVLink/system identity | 0 | metadata default |
| 295 | `MAV_2_UDP_PRT` | MAVLink/system identity | 0 | metadata default |
| 296 | `MNT_DO_STAB` | Mount/gimbal | 0 | metadata default |
| 297 | `MNT_MAN_PITCH` | Mount/gimbal | 0 | metadata default |
| 298 | `MNT_MAN_ROLL` | Mount/gimbal | 0 | metadata default |
| 299 | `MNT_MAN_YAW` | Mount/gimbal | 0 | metadata default |
| 300 | `MNT_MAV_COMPID` | Mount/gimbal | 154 | metadata default |
| 301 | `MNT_MAV_SYSID` | Mount/gimbal | 1 | metadata default |
| 302 | `MNT_MODE_OUT` | Mount/gimbal | 0 | metadata default |
| 303 | `MNT_OB_LOCK_MODE` | Mount/gimbal | 0 | metadata default |
| 304 | `MNT_OB_NORM_MODE` | Mount/gimbal | -1 | metadata default |
| 305 | `MNT_OFF_PITCH` | Mount/gimbal | 0 | metadata default |
| 306 | `MNT_OFF_ROLL` | Mount/gimbal | 0 | metadata default |
| 307 | `MNT_OFF_YAW` | Mount/gimbal | 0 | metadata default |
| 308 | `MNT_RANGE_PITCH` | Mount/gimbal | 360 | metadata default |
| 309 | `MNT_RANGE_ROLL` | Mount/gimbal | 360 | metadata default |
| 310 | `MNT_RANGE_YAW` | Mount/gimbal | 360 | metadata default |
| 311 | `MNT_RATE_PITCH` | Mount/gimbal | 30 | metadata default |
| 312 | `MNT_RATE_YAW` | Mount/gimbal | 30 | metadata default |
| 313 | `NAV_AH_ALT` | Navigation | 600 | metadata default |
| 314 | `NAV_AH_LAT` | Navigation | -265847810 | metadata default |
| 315 | `NAV_AH_LON` | Navigation | 1518423250 | metadata default |
| 316 | `PWM_AUX_DIS7` | Actuator output | -1 | metadata default |
| 317 | `PWM_AUX_DIS8` | Actuator output | -1 | metadata default |
| 318 | `PWM_AUX_FAIL7` | Actuator output | -1 | metadata default |
| 319 | `PWM_AUX_FAIL8` | Actuator output | -1 | metadata default |
| 320 | `PWM_AUX_MAX7` | Actuator output | -1 | metadata default |
| 321 | `PWM_AUX_MAX8` | Actuator output | -1 | metadata default |
| 322 | `PWM_AUX_MIN7` | Actuator output | -1 | metadata default |
| 323 | `PWM_AUX_MIN8` | Actuator output | -1 | metadata default |
| 324 | `PWM_AUX_RATE1` | Actuator output | 50 | metadata default |
| 325 | `PWM_AUX_REV7` | Actuator output | 0 | metadata default |
| 326 | `PWM_AUX_REV8` | Actuator output | 0 | metadata default |
| 327 | `PWM_AUX_TRIM7` | Actuator output | 0 | metadata default |
| 328 | `PWM_AUX_TRIM8` | Actuator output | 0 | metadata default |
| 329 | `PWM_EXTRA_DIS1` | Actuator output | -1 | metadata default |
| 330 | `PWM_EXTRA_DIS2` | Actuator output | -1 | metadata default |
| 331 | `PWM_EXTRA_DIS3` | Actuator output | -1 | metadata default |
| 332 | `PWM_EXTRA_DIS4` | Actuator output | -1 | metadata default |
| 333 | `PWM_EXTRA_DIS5` | Actuator output | -1 | metadata default |
| 334 | `PWM_EXTRA_DIS6` | Actuator output | -1 | metadata default |
| 335 | `PWM_EXTRA_DIS7` | Actuator output | -1 | metadata default |
| 336 | `PWM_EXTRA_DIS8` | Actuator output | -1 | metadata default |
| 337 | `PWM_EXTRA_DISARM` | Actuator output | 1500 | metadata default |
| 338 | `PWM_EXTRA_FAIL1` | Actuator output | 0 | metadata default |
| 339 | `PWM_EXTRA_FAIL2` | Actuator output | 0 | metadata default |
| 340 | `PWM_EXTRA_FAIL3` | Actuator output | 0 | metadata default |
| 341 | `PWM_EXTRA_FAIL4` | Actuator output | 0 | metadata default |
| 342 | `PWM_EXTRA_FAIL5` | Actuator output | 0 | metadata default |
| 343 | `PWM_EXTRA_FAIL6` | Actuator output | 0 | metadata default |
| 344 | `PWM_EXTRA_FAIL7` | Actuator output | 0 | metadata default |
| 345 | `PWM_EXTRA_FAIL8` | Actuator output | 0 | metadata default |
| 346 | `PWM_EXTRA_MAX` | Actuator output | 2000 | metadata default |
| 347 | `PWM_EXTRA_MAX1` | Actuator output | -1 | metadata default |
| 348 | `PWM_EXTRA_MAX2` | Actuator output | -1 | metadata default |
| 349 | `PWM_EXTRA_MAX3` | Actuator output | -1 | metadata default |
| 350 | `PWM_EXTRA_MAX4` | Actuator output | -1 | metadata default |
| 351 | `PWM_EXTRA_MAX5` | Actuator output | -1 | metadata default |
| 352 | `PWM_EXTRA_MAX6` | Actuator output | -1 | metadata default |
| 353 | `PWM_EXTRA_MAX7` | Actuator output | -1 | metadata default |
| 354 | `PWM_EXTRA_MAX8` | Actuator output | -1 | metadata default |
| 355 | `PWM_EXTRA_MIN` | Actuator output | 1000 | metadata default |
| 356 | `PWM_EXTRA_MIN1` | Actuator output | -1 | metadata default |
| 357 | `PWM_EXTRA_MIN2` | Actuator output | -1 | metadata default |
| 358 | `PWM_EXTRA_MIN3` | Actuator output | -1 | metadata default |
| 359 | `PWM_EXTRA_MIN4` | Actuator output | -1 | metadata default |
| 360 | `PWM_EXTRA_MIN5` | Actuator output | -1 | metadata default |
| 361 | `PWM_EXTRA_MIN6` | Actuator output | -1 | metadata default |
| 362 | `PWM_EXTRA_MIN7` | Actuator output | -1 | metadata default |
| 363 | `PWM_EXTRA_MIN8` | Actuator output | -1 | metadata default |
| 364 | `PWM_EXTRA_RATE` | Actuator output | 50 | metadata default |
| 365 | `PWM_EXTRA_RATE1` | Actuator output | 50 | metadata default |
| 366 | `PWM_EXTRA_REV1` | Actuator output | 0 | metadata default |
| 367 | `PWM_EXTRA_REV2` | Actuator output | 0 | metadata default |
| 368 | `PWM_EXTRA_REV3` | Actuator output | 0 | metadata default |
| 369 | `PWM_EXTRA_REV4` | Actuator output | 0 | metadata default |
| 370 | `PWM_EXTRA_REV5` | Actuator output | 0 | metadata default |
| 371 | `PWM_EXTRA_REV6` | Actuator output | 0 | metadata default |
| 372 | `PWM_EXTRA_REV7` | Actuator output | 0 | metadata default |
| 373 | `PWM_EXTRA_REV8` | Actuator output | 0 | metadata default |
| 374 | `PWM_EXTRA_TRIM1` | Actuator output | 0 | metadata default |
| 375 | `PWM_EXTRA_TRIM2` | Actuator output | 0 | metadata default |
| 376 | `PWM_EXTRA_TRIM3` | Actuator output | 0 | metadata default |
| 377 | `PWM_EXTRA_TRIM4` | Actuator output | 0 | metadata default |
| 378 | `PWM_EXTRA_TRIM5` | Actuator output | 0 | metadata default |
| 379 | `PWM_EXTRA_TRIM6` | Actuator output | 0 | metadata default |
| 380 | `PWM_EXTRA_TRIM7` | Actuator output | 0 | metadata default |
| 381 | `PWM_EXTRA_TRIM8` | Actuator output | 0 | metadata default |
| 382 | `PWM_MAIN_DIS10` | Actuator output | -1 | metadata default |
| 383 | `PWM_MAIN_DIS11` | Actuator output | -1 | metadata default |
| 384 | `PWM_MAIN_DIS12` | Actuator output | -1 | metadata default |
| 385 | `PWM_MAIN_DIS13` | Actuator output | -1 | metadata default |
| 386 | `PWM_MAIN_DIS14` | Actuator output | -1 | metadata default |
| 387 | `PWM_MAIN_DIS9` | Actuator output | -1 | metadata default |
| 388 | `PWM_MAIN_FAIL10` | Actuator output | -1 | metadata default |
| 389 | `PWM_MAIN_FAIL11` | Actuator output | -1 | metadata default |
| 390 | `PWM_MAIN_FAIL12` | Actuator output | -1 | metadata default |
| 391 | `PWM_MAIN_FAIL13` | Actuator output | -1 | metadata default |
| 392 | `PWM_MAIN_FAIL14` | Actuator output | -1 | metadata default |
| 393 | `PWM_MAIN_FAIL9` | Actuator output | -1 | metadata default |
| 394 | `PWM_MAIN_MAX10` | Actuator output | -1 | metadata default |
| 395 | `PWM_MAIN_MAX11` | Actuator output | -1 | metadata default |
| 396 | `PWM_MAIN_MAX12` | Actuator output | -1 | metadata default |
| 397 | `PWM_MAIN_MAX13` | Actuator output | -1 | metadata default |
| 398 | `PWM_MAIN_MAX14` | Actuator output | -1 | metadata default |
| 399 | `PWM_MAIN_MAX9` | Actuator output | -1 | metadata default |
| 400 | `PWM_MAIN_MIN10` | Actuator output | -1 | metadata default |
| 401 | `PWM_MAIN_MIN11` | Actuator output | -1 | metadata default |
| 402 | `PWM_MAIN_MIN12` | Actuator output | -1 | metadata default |
| 403 | `PWM_MAIN_MIN13` | Actuator output | -1 | metadata default |
| 404 | `PWM_MAIN_MIN14` | Actuator output | -1 | metadata default |
| 405 | `PWM_MAIN_MIN9` | Actuator output | -1 | metadata default |
| 406 | `PWM_MAIN_RATE1` | Actuator output | 50 | metadata default |
| 407 | `PWM_MAIN_REV10` | Actuator output | 0 | metadata default |
| 408 | `PWM_MAIN_REV11` | Actuator output | 0 | metadata default |
| 409 | `PWM_MAIN_REV12` | Actuator output | 0 | metadata default |
| 410 | `PWM_MAIN_REV13` | Actuator output | 0 | metadata default |
| 411 | `PWM_MAIN_REV14` | Actuator output | 0 | metadata default |
| 412 | `PWM_MAIN_REV9` | Actuator output | 0 | metadata default |
| 413 | `PWM_MAIN_TRIM10` | Actuator output | 0 | metadata default |
| 414 | `PWM_MAIN_TRIM11` | Actuator output | 0 | metadata default |
| 415 | `PWM_MAIN_TRIM12` | Actuator output | 0 | metadata default |
| 416 | `PWM_MAIN_TRIM13` | Actuator output | 0 | metadata default |
| 417 | `PWM_MAIN_TRIM14` | Actuator output | 0 | metadata default |
| 418 | `PWM_MAIN_TRIM9` | Actuator output | 0 | metadata default |
| 419 | `RV_YAW_P` | Other | 0.1 | metadata default |
| 420 | `RWTO_AIRSPD_SCL` | Other | 1.3 | metadata default |
| 421 | `RWTO_HDG` | Other | 0 | metadata default |
| 422 | `RWTO_MAX_PITCH` | Other | 20 | metadata default |
| 423 | `RWTO_MAX_ROLL` | Other | 25 | metadata default |
| 424 | `RWTO_MAX_THR` | Other | 1 | metadata default |
| 425 | `RWTO_NAV_ALT` | Other | 5 | metadata default |
| 426 | `RWTO_PSP` | Other | 0 | metadata default |
| 427 | `RWTO_RAMP_TIME` | Other | 2 | metadata default |
| 428 | `RWTO_TKOFF` | Other | 0 | metadata default |
| 429 | `SENS_DPRES_ANSC` | Sensor selection/offset | 0 | metadata default |
| 430 | `SENS_INT_BARO_EN` | Sensor selection/offset | 1 | metadata default |
| 431 | `SIM_BAT_DRAIN` | Other | 60 | metadata default |
| 432 | `SIM_BAT_MIN_PCT` | Other | 50 | metadata default |
| 433 | `TC_A0_ID` | Other | 0 | metadata default |
| 434 | `TC_A0_TMAX` | Other | 100 | metadata default |
| 435 | `TC_A0_TMIN` | Other | 0 | metadata default |
| 436 | `TC_A0_TREF` | Other | 25 | metadata default |
| 437 | `TC_A0_X0_0` | Other | 0 | metadata default |
| 438 | `TC_A0_X0_1` | Other | 0 | metadata default |
| 439 | `TC_A0_X0_2` | Other | 0 | metadata default |
| 440 | `TC_A0_X1_0` | Other | 0 | metadata default |
| 441 | `TC_A0_X1_1` | Other | 0 | metadata default |
| 442 | `TC_A0_X1_2` | Other | 0 | metadata default |
| 443 | `TC_A0_X2_0` | Other | 0 | metadata default |
| 444 | `TC_A0_X2_1` | Other | 0 | metadata default |
| 445 | `TC_A0_X2_2` | Other | 0 | metadata default |
| 446 | `TC_A0_X3_0` | Other | 0 | metadata default |
| 447 | `TC_A0_X3_1` | Other | 0 | metadata default |
| 448 | `TC_A0_X3_2` | Other | 0 | metadata default |
| 449 | `TC_A1_ID` | Other | 0 | metadata default |
| 450 | `TC_A1_TMAX` | Other | 100 | metadata default |
| 451 | `TC_A1_TMIN` | Other | 0 | metadata default |
| 452 | `TC_A1_TREF` | Other | 25 | metadata default |
| 453 | `TC_A1_X0_0` | Other | 0 | metadata default |
| 454 | `TC_A1_X0_1` | Other | 0 | metadata default |
| 455 | `TC_A1_X0_2` | Other | 0 | metadata default |
| 456 | `TC_A1_X1_0` | Other | 0 | metadata default |
| 457 | `TC_A1_X1_1` | Other | 0 | metadata default |
| 458 | `TC_A1_X1_2` | Other | 0 | metadata default |
| 459 | `TC_A1_X2_0` | Other | 0 | metadata default |
| 460 | `TC_A1_X2_1` | Other | 0 | metadata default |
| 461 | `TC_A1_X2_2` | Other | 0 | metadata default |
| 462 | `TC_A1_X3_0` | Other | 0 | metadata default |
| 463 | `TC_A1_X3_1` | Other | 0 | metadata default |
| 464 | `TC_A1_X3_2` | Other | 0 | metadata default |
| 465 | `TC_A2_ID` | Other | 0 | metadata default |
| 466 | `TC_A2_TMAX` | Other | 100 | metadata default |
| 467 | `TC_A2_TMIN` | Other | 0 | metadata default |
| 468 | `TC_A2_TREF` | Other | 25 | metadata default |
| 469 | `TC_A2_X0_0` | Other | 0 | metadata default |
| 470 | `TC_A2_X0_1` | Other | 0 | metadata default |
| 471 | `TC_A2_X0_2` | Other | 0 | metadata default |
| 472 | `TC_A2_X1_0` | Other | 0 | metadata default |
| 473 | `TC_A2_X1_1` | Other | 0 | metadata default |
| 474 | `TC_A2_X1_2` | Other | 0 | metadata default |
| 475 | `TC_A2_X2_0` | Other | 0 | metadata default |
| 476 | `TC_A2_X2_1` | Other | 0 | metadata default |
| 477 | `TC_A2_X2_2` | Other | 0 | metadata default |
| 478 | `TC_A2_X3_0` | Other | 0 | metadata default |
| 479 | `TC_A2_X3_1` | Other | 0 | metadata default |
| 480 | `TC_A2_X3_2` | Other | 0 | metadata default |
| 481 | `TC_A3_ID` | Other | 0 | metadata default |
| 482 | `TC_A3_TMAX` | Other | 100 | metadata default |
| 483 | `TC_A3_TMIN` | Other | 0 | metadata default |
| 484 | `TC_A3_TREF` | Other | 25 | metadata default |
| 485 | `TC_A3_X0_0` | Other | 0 | metadata default |
| 486 | `TC_A3_X0_1` | Other | 0 | metadata default |
| 487 | `TC_A3_X0_2` | Other | 0 | metadata default |
| 488 | `TC_A3_X1_0` | Other | 0 | metadata default |
| 489 | `TC_A3_X1_1` | Other | 0 | metadata default |
| 490 | `TC_A3_X1_2` | Other | 0 | metadata default |
| 491 | `TC_A3_X2_0` | Other | 0 | metadata default |
| 492 | `TC_A3_X2_1` | Other | 0 | metadata default |
| 493 | `TC_A3_X2_2` | Other | 0 | metadata default |
| 494 | `TC_A3_X3_0` | Other | 0 | metadata default |
| 495 | `TC_A3_X3_1` | Other | 0 | metadata default |
| 496 | `TC_A3_X3_2` | Other | 0 | metadata default |
| 497 | `TC_B0_ID` | Other | 0 | metadata default |
| 498 | `TC_B0_TMAX` | Other | 75 | metadata default |
| 499 | `TC_B0_TMIN` | Other | 5 | metadata default |
| 500 | `TC_B0_TREF` | Other | 40 | metadata default |
| 501 | `TC_B0_X0` | Other | 0 | metadata default |
| 502 | `TC_B0_X1` | Other | 0 | metadata default |
| 503 | `TC_B0_X2` | Other | 0 | metadata default |
| 504 | `TC_B0_X3` | Other | 0 | metadata default |
| 505 | `TC_B0_X4` | Other | 0 | metadata default |
| 506 | `TC_B0_X5` | Other | 0 | metadata default |
| 507 | `TC_B1_ID` | Other | 0 | metadata default |
| 508 | `TC_B1_TMAX` | Other | 75 | metadata default |
| 509 | `TC_B1_TMIN` | Other | 5 | metadata default |
| 510 | `TC_B1_TREF` | Other | 40 | metadata default |
| 511 | `TC_B1_X0` | Other | 0 | metadata default |
| 512 | `TC_B1_X1` | Other | 0 | metadata default |
| 513 | `TC_B1_X2` | Other | 0 | metadata default |
| 514 | `TC_B1_X3` | Other | 0 | metadata default |
| 515 | `TC_B1_X4` | Other | 0 | metadata default |
| 516 | `TC_B1_X5` | Other | 0 | metadata default |
| 517 | `TC_B2_ID` | Other | 0 | metadata default |
| 518 | `TC_B2_TMAX` | Other | 75 | metadata default |
| 519 | `TC_B2_TMIN` | Other | 5 | metadata default |
| 520 | `TC_B2_TREF` | Other | 40 | metadata default |
| 521 | `TC_B2_X0` | Other | 0 | metadata default |
| 522 | `TC_B2_X1` | Other | 0 | metadata default |
| 523 | `TC_B2_X2` | Other | 0 | metadata default |
| 524 | `TC_B2_X3` | Other | 0 | metadata default |
| 525 | `TC_B2_X4` | Other | 0 | metadata default |
| 526 | `TC_B2_X5` | Other | 0 | metadata default |
| 527 | `TC_B3_ID` | Other | 0 | metadata default |
| 528 | `TC_B3_TMAX` | Other | 75 | metadata default |
| 529 | `TC_B3_TMIN` | Other | 5 | metadata default |
| 530 | `TC_B3_TREF` | Other | 40 | metadata default |
| 531 | `TC_B3_X0` | Other | 0 | metadata default |
| 532 | `TC_B3_X1` | Other | 0 | metadata default |
| 533 | `TC_B3_X2` | Other | 0 | metadata default |
| 534 | `TC_B3_X3` | Other | 0 | metadata default |
| 535 | `TC_B3_X4` | Other | 0 | metadata default |
| 536 | `TC_B3_X5` | Other | 0 | metadata default |
| 537 | `TC_G0_ID` | Other | 0 | metadata default |
| 538 | `TC_G0_TMAX` | Other | 100 | metadata default |
| 539 | `TC_G0_TMIN` | Other | 0 | metadata default |
| 540 | `TC_G0_TREF` | Other | 25 | metadata default |
| 541 | `TC_G0_X0_0` | Other | 0 | metadata default |
| 542 | `TC_G0_X0_1` | Other | 0 | metadata default |
| 543 | `TC_G0_X0_2` | Other | 0 | metadata default |
| 544 | `TC_G0_X1_0` | Other | 0 | metadata default |
| 545 | `TC_G0_X1_1` | Other | 0 | metadata default |
| 546 | `TC_G0_X1_2` | Other | 0 | metadata default |
| 547 | `TC_G0_X2_0` | Other | 0 | metadata default |
| 548 | `TC_G0_X2_1` | Other | 0 | metadata default |
| 549 | `TC_G0_X2_2` | Other | 0 | metadata default |
| 550 | `TC_G0_X3_0` | Other | 0 | metadata default |
| 551 | `TC_G0_X3_1` | Other | 0 | metadata default |
| 552 | `TC_G0_X3_2` | Other | 0 | metadata default |
| 553 | `TC_G1_ID` | Other | 0 | metadata default |
| 554 | `TC_G1_TMAX` | Other | 100 | metadata default |
| 555 | `TC_G1_TMIN` | Other | 0 | metadata default |
| 556 | `TC_G1_TREF` | Other | 25 | metadata default |
| 557 | `TC_G1_X0_0` | Other | 0 | metadata default |
| 558 | `TC_G1_X0_1` | Other | 0 | metadata default |
| 559 | `TC_G1_X0_2` | Other | 0 | metadata default |
| 560 | `TC_G1_X1_0` | Other | 0 | metadata default |
| 561 | `TC_G1_X1_1` | Other | 0 | metadata default |
| 562 | `TC_G1_X1_2` | Other | 0 | metadata default |
| 563 | `TC_G1_X2_0` | Other | 0 | metadata default |
| 564 | `TC_G1_X2_1` | Other | 0 | metadata default |
| 565 | `TC_G1_X2_2` | Other | 0 | metadata default |
| 566 | `TC_G1_X3_0` | Other | 0 | metadata default |
| 567 | `TC_G1_X3_1` | Other | 0 | metadata default |
| 568 | `TC_G1_X3_2` | Other | 0 | metadata default |
| 569 | `TC_G2_ID` | Other | 0 | metadata default |
| 570 | `TC_G2_TMAX` | Other | 100 | metadata default |
| 571 | `TC_G2_TMIN` | Other | 0 | metadata default |
| 572 | `TC_G2_TREF` | Other | 25 | metadata default |
| 573 | `TC_G2_X0_0` | Other | 0 | metadata default |
| 574 | `TC_G2_X0_1` | Other | 0 | metadata default |
| 575 | `TC_G2_X0_2` | Other | 0 | metadata default |
| 576 | `TC_G2_X1_0` | Other | 0 | metadata default |
| 577 | `TC_G2_X1_1` | Other | 0 | metadata default |
| 578 | `TC_G2_X1_2` | Other | 0 | metadata default |
| 579 | `TC_G2_X2_0` | Other | 0 | metadata default |
| 580 | `TC_G2_X2_1` | Other | 0 | metadata default |
| 581 | `TC_G2_X2_2` | Other | 0 | metadata default |
| 582 | `TC_G2_X3_0` | Other | 0 | metadata default |
| 583 | `TC_G2_X3_1` | Other | 0 | metadata default |
| 584 | `TC_G2_X3_2` | Other | 0 | metadata default |
| 585 | `TC_G3_ID` | Other | 0 | metadata default |
| 586 | `TC_G3_TMAX` | Other | 100 | metadata default |
| 587 | `TC_G3_TMIN` | Other | 0 | metadata default |
| 588 | `TC_G3_TREF` | Other | 25 | metadata default |
| 589 | `TC_G3_X0_0` | Other | 0 | metadata default |
| 590 | `TC_G3_X0_1` | Other | 0 | metadata default |
| 591 | `TC_G3_X0_2` | Other | 0 | metadata default |
| 592 | `TC_G3_X1_0` | Other | 0 | metadata default |
| 593 | `TC_G3_X1_1` | Other | 0 | metadata default |
| 594 | `TC_G3_X1_2` | Other | 0 | metadata default |
| 595 | `TC_G3_X2_0` | Other | 0 | metadata default |
| 596 | `TC_G3_X2_1` | Other | 0 | metadata default |
| 597 | `TC_G3_X2_2` | Other | 0 | metadata default |
| 598 | `TC_G3_X3_0` | Other | 0 | metadata default |
| 599 | `TC_G3_X3_1` | Other | 0 | metadata default |
| 600 | `TC_G3_X3_2` | Other | 0 | metadata default |
| 601 | `TEST_1` | Other | 2 | metadata default |
| 602 | `TEST_2` | Other | 4 | metadata default |
| 603 | `TEST_3` | Other | 5 | metadata default |
| 604 | `TEST_D` | Other | 0.01 | metadata default |
| 605 | `TEST_DEV` | Other | 2 | metadata default |
| 606 | `TEST_D_LP` | Other | 10 | metadata default |
| 607 | `TEST_HP` | Other | 10 | metadata default |
| 608 | `TEST_I` | Other | 0.1 | metadata default |
| 609 | `TEST_I_MAX` | Other | 1 | metadata default |
| 610 | `TEST_LP` | Other | 10 | metadata default |
| 611 | `TEST_MAX` | Other | 1 | metadata default |
| 612 | `TEST_MEAN` | Other | 1 | metadata default |
| 613 | `TEST_MIN` | Other | -1 | metadata default |
| 614 | `TEST_P` | Other | 0.2 | metadata default |
| 615 | `TEST_PARAMS` | Other | 12345678 | metadata default |
| 616 | `TEST_RC2_X` | Other | 16 | metadata default |
| 617 | `TEST_RC_X` | Other | 8 | metadata default |
| 618 | `TEST_TRIM` | Other | 0.5 | metadata default |
| 619 | `TRIG_ACT_TIME` | Trigger/camera | 40 | metadata default |
| 620 | `TRIG_DISTANCE` | Trigger/camera | 25 | metadata default |
| 621 | `TRIG_INTERFACE` | Trigger/camera | 3 | rcS:157 set-default |
| 622 | `TRIG_INTERVAL` | Trigger/camera | 40 | metadata default |
| 623 | `TRIG_MIN_INTERVA` | Trigger/camera | 1 | metadata default |
| 624 | `TRIG_PINS` | Trigger/camera | 56 | metadata default |
| 625 | `TRIG_PINS_EX` | Trigger/camera | 0 | metadata default |
| 626 | `TRIG_POLARITY` | Trigger/camera | 0 | metadata default |
| 627 | `TRIG_PWM_NEUTRAL` | Trigger/camera | 1500 | metadata default |
| 628 | `TRIG_PWM_SHOOT` | Trigger/camera | 1900 | metadata default |
| 629 | `TRIM_PITCH` | Other | 0 | metadata default |
| 630 | `TRIM_ROLL` | Other | 0 | metadata default |
| 631 | `TRIM_YAW` | Other | 0 | metadata default |
| 632 | `UUV_DIRCT_PITCH` | Other | 0 | metadata default |
| 633 | `UUV_DIRCT_ROLL` | Other | 0 | metadata default |
| 634 | `UUV_DIRCT_THRUST` | Other | 0 | metadata default |
| 635 | `UUV_DIRCT_YAW` | Other | 0 | metadata default |
| 636 | `UUV_GAIN_X_D` | Other | 0.2 | metadata default |
| 637 | `UUV_GAIN_X_P` | Other | 1 | metadata default |
| 638 | `UUV_GAIN_Y_D` | Other | 0.2 | metadata default |
| 639 | `UUV_GAIN_Y_P` | Other | 1 | metadata default |
| 640 | `UUV_GAIN_Z_D` | Other | 0.2 | metadata default |
| 641 | `UUV_GAIN_Z_P` | Other | 1 | metadata default |
| 642 | `UUV_INPUT_MODE` | Other | 0 | metadata default |
| 643 | `UUV_PITCH_D` | Other | 2 | metadata default |
| 644 | `UUV_PITCH_P` | Other | 4 | metadata default |
| 645 | `UUV_ROLL_D` | Other | 1.5 | metadata default |
| 646 | `UUV_ROLL_P` | Other | 4 | metadata default |
| 647 | `UUV_SKIP_CTRL` | Other | 0 | metadata default |
| 648 | `UUV_STAB_MODE` | Other | 1 | metadata default |
| 649 | `UUV_YAW_D` | Other | 2 | metadata default |
| 650 | `UUV_YAW_P` | Other | 4 | metadata default |
| 651 | `VT_ARSP_BLEND` | VTOL | 8 | metadata default |
| 652 | `VT_ARSP_TRANS` | VTOL | 10 | metadata default |
| 653 | `VT_B_DEC_FF` | VTOL | 0.12 | metadata default |
| 654 | `VT_B_DEC_I` | VTOL | 0.1 | metadata default |
| 655 | `VT_B_REV_OUT` | VTOL | 0 | metadata default |
| 656 | `VT_B_TRANS_DUR` | VTOL | 4 | metadata default |
| 657 | `VT_B_TRANS_RAMP` | VTOL | 3 | metadata default |
| 658 | `VT_B_TRANS_THR` | VTOL | 0 | metadata default |
| 659 | `VT_DWN_PITCH_MAX` | VTOL | 5 | metadata default |
| 660 | `VT_ELEV_MC_LOCK` | VTOL | 1 | metadata default |
| 661 | `VT_FWD_THRUST_EN` | VTOL | 0 | metadata default |
| 662 | `VT_FWD_THRUST_SC` | VTOL | 0.7 | metadata default |
| 663 | `VT_FW_ALT_ERR` | VTOL | 0 | metadata default |
| 664 | `VT_FW_DIFTHR_EN` | VTOL | 0 | metadata default |
| 665 | `VT_FW_DIFTHR_SC` | VTOL | 0.1 | metadata default |
| 666 | `VT_FW_MIN_ALT` | VTOL | 0 | metadata default |
| 667 | `VT_FW_MOT_OFFID` | VTOL | 0 | metadata default |
| 668 | `VT_FW_PERM_STAB` | VTOL | 0 | metadata default |
| 669 | `VT_FW_QC_P` | VTOL | 0 | metadata default |
| 670 | `VT_FW_QC_R` | VTOL | 0 | metadata default |
| 671 | `VT_F_TRANS_DUR` | VTOL | 5 | metadata default |
| 672 | `VT_F_TRANS_THR` | VTOL | 1 | metadata default |
| 673 | `VT_F_TR_OL_TM` | VTOL | 6 | metadata default |
| 674 | `VT_IDLE_PWM_MC` | VTOL | 900 | metadata default |
| 675 | `VT_MC_ON_FMU` | VTOL | 0 | metadata default |
| 676 | `VT_MOT_ID` | VTOL | 0 | metadata default |
| 677 | `VT_PSHER_RMP_DT` | VTOL | 3 | metadata default |
| 678 | `VT_TILT_FW` | VTOL | 1 | metadata default |
| 679 | `VT_TILT_MC` | VTOL | 0 | metadata default |
| 680 | `VT_TILT_SPINUP` | VTOL | 0 | metadata default |
| 681 | `VT_TILT_TRANS` | VTOL | 0.3 | metadata default |
| 682 | `VT_TRANS_MIN_TM` | VTOL | 2 | metadata default |
| 683 | `VT_TRANS_P2_DUR` | VTOL | 0.5 | metadata default |
| 684 | `VT_TRANS_TIMEOUT` | VTOL | 15 | metadata default |
| 685 | `VT_TYPE` | VTOL | 0 | metadata default |
| 686 | `WV_GAIN` | Other | 1 | metadata default |
| 687 | `WV_ROLL_MIN` | Other | 1 | metadata default |
| 688 | `WV_YRATE_MAX` | Other | 90 | metadata default |
| 689 | `ctl_bw` | Other | 75 | metadata default |
| 690 | `ctl_dir` | Other | 1 | metadata default |
| 691 | `ctl_gain` | Other | 1 | metadata default |
| 692 | `ctl_hz_idle` | Other | 3.5 | metadata default |
| 693 | `ctl_start_rate` | Other | 25 | metadata default |
| 694 | `esc_index` | Other | 0 | metadata default |
| 695 | `gnss.dyn_model` | Other | 2 | metadata default |
| 696 | `gnss.old_fix_msg` | Other | 1 | metadata default |
| 697 | `gnss.warn_dimens` | Other | 0 | metadata default |
| 698 | `gnss.warn_sats` | Other | 0 | metadata default |
| 699 | `id_ext_status` | Other | 20034 | metadata default |
| 700 | `int_ext_status` | Other | 50000 | metadata default |
| 701 | `int_status` | Other | 50000 | metadata default |
| 702 | `mot_i_max` | Other | 12 | metadata default |
| 703 | `mot_kv` | Other | 2300 | metadata default |
| 704 | `mot_ls` | Other | 0 | metadata default |
| 705 | `mot_num_poles` | Other | 14 | metadata default |
| 706 | `mot_rs` | Other | 0 | metadata default |
| 707 | `mot_v_accel` | Other | 0.5 | metadata default |
| 708 | `mot_v_max` | Other | 14.8 | metadata default |
| 709 | `uavcan.pubp-pres` | Other | 0 | metadata default |
