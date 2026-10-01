#!/usr/bin/env python3
"""Time render_fs150_indoor_sdf.py for a fleet, one process per robot.

Core renders every FS150 in its own process (simulation.render-fs150-sdf), so
this does the same: one robot per run, each with its own namespace and model
name. It reports the wall time of the whole fleet, the median and the first
render, and the CPU the renderer processes used.

With --compare the fleet is rendered without the lidar (the floor), with the
lidar and the render cache off (what every render cost before the cache), with
the lidar and a fresh empty cache directory, and again with the now warm cache.
It fails unless every robot's SDF is byte for byte the same with and without
the cache.

Needs `rospack` and `xacro` on PATH (the ROS install or stand-ins). Examples:

  test/render_benchmark.py --compare --robots 24
  test/render_benchmark.py --compare --robots 24 --parallel 8
  test/render_benchmark.py --renderer old_renderer.py --robots 24   # a baseline
"""
import argparse
import concurrent.futures
import os
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
CACHE_ENV = 'XGC2_FS150_RENDER_CACHE_DIR'


def render_command(renderer, base_sdf, output, index, acceleration):
    name = 'uav%d' % index
    command = [sys.executable, str(renderer), '--base-sdf', str(base_sdf), '--output', str(output),
               '--robot-namespace', name, '--model-name', name, '--print-path']
    if acceleration:
        command += ['--enable-simple-lidar', 'true', '--simple-lidar-acceleration', acceleration]
    return command


def render_fleet(renderer, base_sdf, outputs, robots, parallel, acceleration, cache):
    """Render the fleet; return (wall seconds, per-robot seconds, renderer CPU seconds)."""
    outputs.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.pop(CACHE_ENV, None)
    if cache is not None:
        environment[CACHE_ENV] = cache

    def one(index):
        started = time.perf_counter()
        subprocess.run(render_command(renderer, base_sdf, outputs / ('uav%d.sdf' % index), index, acceleration),
                       check=True, stdout=subprocess.DEVNULL, env=environment)
        return time.perf_counter() - started

    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as pool:
        durations = list(pool.map(one, range(1, robots + 1)))
    wall = time.perf_counter() - started
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    return wall, durations, cpu


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--renderer', default=str(PKG / 'scripts/render_fs150_indoor_sdf.py'))
    parser.add_argument('--base-sdf', default=str(PKG / 'models/fs150/iris.sdf'))
    parser.add_argument('--robots', type=int, default=24)
    parser.add_argument('--parallel', type=int, default=1, help='renders running at once')
    parser.add_argument('--acceleration', choices=('cpu', 'gpu'), default='gpu')
    parser.add_argument('--compare', action='store_true',
                        help='run the cache-off, cold and warm fleets and require identical SDFs')
    args = parser.parse_args()

    print('%-30s %6s %4s %9s %10s %10s %9s' % ('', 'robots', 'par', 'wall s', 'median s', 'first s', 'cpu s'))
    with tempfile.TemporaryDirectory(prefix='fs150-render-bench-') as scratch:
        scratch = Path(scratch)
        cache = str(scratch / 'cache')
        runs = [('no lidar', None, None)]
        if args.compare:
            runs += [('lidar, cache off', args.acceleration, ''),
                     ('lidar, cache cold', args.acceleration, cache),
                     ('lidar, cache warm', args.acceleration, cache)]
        else:
            runs += [('lidar', args.acceleration, cache)]
        outputs = {}
        for label, acceleration, cache_directory in runs:
            outputs[label] = scratch / label.replace(' ', '-').replace(',', '')
            wall, durations, cpu = render_fleet(args.renderer, args.base_sdf, outputs[label], args.robots,
                                                args.parallel, acceleration, cache_directory)
            print('%-30s %6d %4d %9.2f %10.3f %10.3f %9.2f' % (
                label, args.robots, args.parallel, wall, statistics.median(durations), durations[0], cpu))
        if args.compare:
            baseline = outputs['lidar, cache off']
            differing = [index for index in range(1, args.robots + 1)
                         for label in ('lidar, cache cold', 'lidar, cache warm')
                         if (outputs[label] / ('uav%d.sdf' % index)).read_bytes() !=
                         (baseline / ('uav%d.sdf' % index)).read_bytes()]
            if differing:
                print('FAIL: SDFs differ for robots %s' % sorted(set(differing)), file=sys.stderr)
                return 1
            print('identical: %d robots x 2 cache states, byte for byte' % args.robots)
    return 0


if __name__ == '__main__':
    sys.exit(main())
