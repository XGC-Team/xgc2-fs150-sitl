# RK356x/RK3566 Performance Mode Notes

This note records the operating-system level performance-mode checks done on
the FS150 onboard computer.  The board identifies itself as `rk356x` and runs
Ubuntu 20.04 with a Rockchip 5.10 kernel.

The FS150 onboard computer did not have a high-level performance profile tool
installed during the check:

```text
powerprofilesctl: not found
tuned-adm: not found
cpupower: not found
nvpmodel: not found
```

It does support Linux CPUfreq governors through sysfs.  The tested and
recommended performance-mode operation is therefore a CPU governor change:

```text
interactive -> performance
```

This is a runtime setting.  It may be reset by reboot or by another startup
script unless a persistent service is installed.

## Observed FS150 State

Observed host:

```text
hostname: rk356x
kernel: Linux 5.10.160 aarch64
OS: Ubuntu 20.04.6 LTS
online CPUs: 0-3
CPU driver: cpufreq-dt
CPU frequency range: 408000 - 1800000 kHz
```

Available CPU governors:

```text
interactive conservative ondemand userspace powersave performance schedutil
```

Before switching:

```text
cpu0-3 governor = interactive
```

After switching:

```text
cpu0-3 governor = performance
cpu0-3 frequency = 1800000 kHz
```

One-minute temperature observation after switching CPU governor to
`performance`:

```text
soc-thermal: 53.8-55.0 C
gpu-thermal: 52.5-53.1 C
```

No thermal rise was observed during this short low-load check.  Re-check under
the real workload because controller, vision, logging, and network load can
change the thermal behavior.

## Governor Modes

| Governor | Behavior | Use on FS150 |
| --- | --- | --- |
| `performance` | Keeps CPU frequency at or near the maximum. | Best for latency-sensitive tests and high-rate telemetry/control debugging. |
| `powersave` | Keeps CPU frequency at or near the minimum. | Not suitable for high-rate control or telemetry tests. |
| `userspace` | Lets a userspace tool select the frequency. | Only useful if a separate frequency manager is used. |
| `ondemand` | Raises frequency when CPU load increases and lowers it when idle. | General dynamic mode, but can add frequency-scaling latency. |
| `conservative` | Like `ondemand`, but changes frequency more slowly. | Lower power, slower response; not recommended for timing-sensitive tests. |
| `interactive` | Dynamic mode that raises frequency aggressively for responsiveness. | Current default on the aircraft; usually usable, but not fixed-frequency. |
| `schedutil` | Uses Linux scheduler utilization to select frequency. | Modern dynamic mode; behavior depends on kernel and board tuning. |

For deterministic timing experiments, `performance` is easier to reason about
than `interactive`, because all cores stay at the maximum CPU frequency.

## Query Current CPU Mode

Run from the host:

```bash
ssh marvsmart@192.168.51.14
```

Then on the onboard computer:

```bash
for p in /sys/devices/system/cpu/cpufreq/policy*; do
  [ -d "$p" ] || continue
  echo "-- $(basename "$p") --"
  for f in related_cpus scaling_driver scaling_available_governors \
           scaling_governor scaling_min_freq scaling_max_freq \
           scaling_cur_freq cpuinfo_min_freq cpuinfo_max_freq; do
    [ -r "$p/$f" ] && printf "%s=%s\n" "$f" "$(cat "$p/$f")"
  done
done
```

Per-core compact view:

```bash
for f in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq; do
  [ -r "$f" ] || continue
  cpu=${f#/sys/devices/system/cpu/}
  cpu=${cpu%%/*}
  gov=$(cat "$(dirname "$f")/scaling_governor" 2>/dev/null || echo unknown)
  printf "%s: %s kHz governor=%s\n" "$cpu" "$(cat "$f")" "$gov"
done
```

## Enable CPU Performance Mode

Save the current governors before changing them:

```bash
backup=/tmp/xgc2_cpu_governors_before_performance
: > "$backup"

for f in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor; do
  [ -r "$f" ] || continue
  printf "%s %s\n" "$f" "$(cat "$f")" >> "$backup"
done

cat "$backup"
```

Switch all CPU cores to `performance`:

```bash
for f in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor; do
  [ -w "$f" ] || continue
  echo performance | sudo tee "$f" >/dev/null
done
```

Verify:

```bash
for f in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor; do
  [ -r "$f" ] || continue
  cpu=${f#/sys/devices/system/cpu/}
  cpu=${cpu%%/*}
  freq_file=$(dirname "$f")/scaling_cur_freq
  printf "%s governor=%s" "$cpu" "$(cat "$f")"
  [ -r "$freq_file" ] && printf " cur_khz=%s" "$(cat "$freq_file")"
  echo
done
```

Expected FS150 result:

```text
cpu0 governor=performance cur_khz=1800000
cpu1 governor=performance cur_khz=1800000
cpu2 governor=performance cur_khz=1800000
cpu3 governor=performance cur_khz=1800000
```

## Restore Previous CPU Mode

If the backup file exists:

```bash
backup=/tmp/xgc2_cpu_governors_before_performance

while read -r file governor; do
  [ -n "$file" ] || continue
  [ -w "$file" ] || continue
  echo "$governor" | sudo tee "$file" >/dev/null
done < "$backup"
```

For the observed FS150 state, this restores:

```text
cpu0-3 governor = interactive
```

To explicitly set all cores back to `interactive`:

```bash
for f in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor; do
  [ -w "$f" ] || continue
  echo interactive | sudo tee "$f" >/dev/null
done
```

## Temperature Monitoring

Single read:

```bash
for z in /sys/class/thermal/thermal_zone*; do
  [ -d "$z" ] || continue
  type=$(cat "$z/type" 2>/dev/null || echo unknown)
  temp=$(cat "$z/temp" 2>/dev/null || echo)
  [ -n "$temp" ] && awk -v n="$type" -v t="$temp" \
    'BEGIN { printf "%s: %.1f C (%s)\n", n, t/1000.0, t }'
done
```

One-minute monitor at 5 second intervals:

```bash
for i in $(seq 1 13); do
  ts=$(date +%H:%M:%S)
  soc=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 0)
  gpu=$(cat /sys/class/thermal/thermal_zone1/temp 2>/dev/null || echo 0)
  freqs=""
  govs=""

  for f in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq; do
    [ -r "$f" ] || continue
    cpu=${f#/sys/devices/system/cpu/}
    cpu=${cpu%%/*}
    freq=$(cat "$f")
    gov=$(cat "$(dirname "$f")/scaling_governor" 2>/dev/null || echo unknown)
    freqs="$freqs $cpu=${freq}kHz"
    govs="$govs $cpu=$gov"
  done

  awk -v i="$i" -v ts="$ts" -v soc="$soc" -v gpu="$gpu" \
      -v freqs="$freqs" -v govs="$govs" \
      'BEGIN { printf "sample=%02d time=%s soc=%.1fC gpu=%.1fC%s%s\n", \
               i, ts, soc/1000.0, gpu/1000.0, freqs, govs }'

  [ "$i" -lt 13 ] && sleep 5
done
```

## Optional Devfreq Devices

The RK356x board also exposes devfreq governors for non-CPU devices:

```text
dmc              governor=dmc_ondemand
fde40000.npu     governor=rknpu_ondemand
fde60000.gpu     governor=simple_ondemand
fdf80200.rkvdec  governor=vdec2_ondemand
```

These devices also list `performance` as an available governor, but they were
not switched during the FS150 CPU performance-mode test.  Leave them unchanged
unless the workload specifically depends on memory, GPU, NPU, or video decode
latency.

Query devfreq state:

```bash
for d in /sys/class/devfreq/*; do
  [ -d "$d" ] || continue
  echo "-- $(basename "$d") --"
  for f in governor available_governors cur_freq min_freq max_freq \
           available_frequencies target_freq; do
    [ -r "$d/$f" ] && printf "%s=%s\n" "$f" "$(cat "$d/$f" 2>/dev/null)"
  done
done
```

Optional devfreq performance command, if a specific test requires it:

```bash
echo performance | sudo tee /sys/class/devfreq/<device>/governor >/dev/null
```

Do not set all devfreq devices to `performance` blindly.  It can increase power
draw and heat without helping CPU-bound MAVROS or controller workloads.

## Persistent Boot-Time Option

The commands above are runtime changes.  To make CPU performance mode
persistent, create a systemd service on the onboard computer:

```bash
sudo tee /etc/systemd/system/xgc2-cpu-performance.service >/dev/null <<'EOF'
[Unit]
Description=Set CPU governor to performance for XGC2 runtime
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'for f in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor; do [ -w "$f" ] && echo performance > "$f"; done'

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable xgc2-cpu-performance.service
sudo systemctl start xgc2-cpu-performance.service
```

Disable persistent performance mode:

```bash
sudo systemctl disable --now xgc2-cpu-performance.service
sudo rm -f /etc/systemd/system/xgc2-cpu-performance.service
sudo systemctl daemon-reload
```

Then restore the desired governor manually, for example:

```bash
for f in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor; do
  [ -w "$f" ] || continue
  echo interactive | sudo tee "$f" >/dev/null
done
```

## Practical Recommendation

For FS150 high-rate MAVROS/IMU and onboard controller tests:

```text
CPU governor: performance
Devfreq governors: leave unchanged unless proven necessary
Temperature: monitor soc-thermal and gpu-thermal under the real workload
```

The observed idle/light-load performance-mode temperature was around
`54-55 C`, which is acceptable for short tests.  Long flight or vision workloads
should be monitored separately.
