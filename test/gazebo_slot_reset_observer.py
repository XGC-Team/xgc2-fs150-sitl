#!/usr/bin/env python3
"""Read-only actual Gazebo/PX4 slot reset observer; never performs a reset.

Run capture before the owning Reconnect, then verify its real receipt after.
Use watch across the entire stop/reset/start interval for sibling and clock
continuity. No reset_world, SetModelState, spawn, replacement or process kill
is issued here; Root's owning workflow/helper remains the action authority.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import threading
import time
import xml.etree.ElementTree as ET


def bounded(call, timeout=3):
    result = queue.Queue()
    def execute():
        try: result.put((True, call()))
        except Exception as error: result.put((False, str(error)))
    threading.Thread(target=execute, daemon=True).start()
    try: success, value = result.get(timeout=timeout)
    except queue.Empty: raise RuntimeError('Gazebo service call timed out; preserve world/clock FAIL')
    if not success: raise RuntimeError(value)
    return value


def vector(value):
    return [value.x, value.y, value.z]


def norm(values):
    return math.sqrt(sum(v*v for v in values))


def proc_start(pid):
    try:
        # Start time identifies the exact old process, even if its PID is reused.
        fields = Path('/proc/{}/stat'.format(pid)).read_text().rsplit(')', 1)[1].split()
        return fields[19]
    except (OSError, IndexError): return None


def stopped_receipt(receipt, model):
    if receipt.get('model') != model or receipt.get('state') != 'Released':
        raise RuntimeError('old slot subtree must be authoritatively Released before reset')
    roles = set()
    for process in receipt.get('processes', []):
        roles.add(process['role'])
        if process.get('state') != 'exited':
            raise RuntimeError('old {} process not confirmed exited'.format(process['role']))
        current = proc_start(int(process['pid']))
        if current is not None and current == str(process['startTime']):
            raise RuntimeError('old owned PID is still alive: {}'.format(process['pid']))
    if not {'px4', 'mavros'} <= roles:
        raise RuntimeError('receipt must cover old PX4 and MAVROS, not just provider send-success')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, required=True,
                        help='frozen {model, namespace, initialPose:{x,y,z,yaw}, renderedSdf, sibling}')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phase', choices=('capture', 'watch', 'verify-reset', 'verify-source-loss'), required=True)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--release-receipt', type=Path)
    parser.add_argument('--duration', type=float, default=2)
    parser.add_argument('--position-tolerance', type=float, default=.05)
    parser.add_argument('--angle-tolerance', type=float, default=.08726646259971647)
    parser.add_argument('--velocity-tolerance', type=float, default=.05)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())
    if spec.get('privateWorld') is not True:
        raise RuntimeError('this entry requires an explicitly private test world; formal station is p1-only')
    for name in ('model', 'namespace', 'initialPose', 'renderedSdf', 'sibling'):
        if name not in spec: raise RuntimeError('missing frozen ' + name)
    initial = spec['initialPose']
    if any(not math.isfinite(float(initial[name])) for name in ('x', 'y', 'z', 'yaw')):
        raise RuntimeError('invalid frozen initialPose')
    joints = [p.findtext('jointName') for p in ET.parse(spec['renderedSdf']).getroot().iter('plugin')
              if Path(p.get('filename', '')).name == 'libgazebo_motor_model.so']
    if len(joints) != 4 or any(not name for name in joints):
        raise RuntimeError('use the actual frozen rendered FS150 SDF with four motor joints')
    import rospy
    from gazebo_msgs.srv import GetJointProperties, GetModelState, GetWorldProperties
    from mavros_msgs.msg import State
    from rosgraph_msgs.msg import Clock
    rospy.init_node('gazebo_slot_reset_observer', anonymous=True, disable_rostime=True)
    fcu, clocks = [], []
    subscriptions = [rospy.Subscriber(spec['namespace'].rstrip('/')+'/mavros/state', State,
                                     lambda m: fcu.append({'connected': m.connected, 'armed': m.armed,
                                                          'mode': m.mode, 'wall': time.monotonic()})),
                     rospy.Subscriber('/clock', Clock,
                                      lambda m: clocks.append((time.monotonic(), m.clock.to_sec())))]
    world = rospy.ServiceProxy('/gazebo/get_world_properties', GetWorldProperties)
    model = rospy.ServiceProxy('/gazebo/get_model_state', GetModelState)
    joint = rospy.ServiceProxy('/gazebo/get_joint_properties', GetJointProperties)
    def body(name):
        state = bounded(lambda: model(name, 'world'))
        if not state.success: raise RuntimeError('actual body lookup failed: '+state.status_message)
        return {'position': vector(state.pose.position),
                'quaternion': [state.pose.orientation.x, state.pose.orientation.y,
                               state.pose.orientation.z, state.pose.orientation.w],
                'velocity': vector(state.twist.linear), 'omega': vector(state.twist.angular)}
    samples, gates = [], {}
    failure = None
    try:
        deadline = time.monotonic()+args.duration
        while time.monotonic() < deadline:
            properties = bounded(world)
            if spec['sibling'] not in properties.model_names:
                raise RuntimeError('sibling world model absent')
            target_present = spec['model'] in properties.model_names
            if not target_present and args.phase != 'watch':
                raise RuntimeError('target world model absent')
            motors = []
            for name in joints if target_present else []:
                status = bounded(lambda name=name: joint(spec['model']+'::'+name))
                if not status.success: raise RuntimeError('rotor observation failed: '+status.status_message)
                motors.append(list(status.rate))
            samples.append({'wall': time.monotonic(), 'simTime': properties.sim_time,
                            'A': body(spec['model']) if target_present else None,
                            'B': body(spec['sibling']), 'rotorRates': motors})
            time.sleep(.05)
        gates['actual_observation'] = bool(samples)
        if args.phase == 'watch':
            gates['clock_not_reset'] = bool(clocks) and all(b[1]>=a[1] for a,b in zip(clocks,clocks[1:]))
            gates['clock_continues'] = len(clocks)>1 and clocks[-1][1]>clocks[0][1]
            gates['clock_no_stall_over_2s'] = len(clocks)>1 and max(b[0]-a[0] for a,b in zip(clocks,clocks[1:]))<2
            gates['sibling_no_teleport'] = all(norm([y-x for x,y in zip(a['B']['position'], b['B']['position'])])<.5
                                                for a,b in zip(samples,samples[1:]))
        if args.phase == 'verify-reset':
            if not args.release_receipt: raise RuntimeError('requires actual old subtree release/PID receipt')
            receipt=json.loads(args.release_receipt.read_text());stopped_receipt(receipt,spec['model'])
            gates['old_provider_px4_mavros_released_and_exited']=True
            target=[initial[name] for name in ('x','y','z')]
            last=samples[-1]['A'];q=last['quaternion'];goal=[0,0,math.sin(initial['yaw']/2),math.cos(initial['yaw']/2)]
            angle=2*math.acos(min(1,abs(sum(a*b for a,b in zip(q,goal)))/norm(q)))
            gates['A_frozen_initialPose'] = norm([a-b for a,b in zip(last['position'],target)])<=args.position_tolerance and angle<=args.angle_tolerance
            gates['A_velocity_omega_clear'] = norm(last['velocity'])<=args.velocity_tolerance and norm(last['omega'])<=args.velocity_tolerance
            gates['A_rotors_clear'] = all(abs(value)<=args.velocity_tolerance for rates in samples[-1]['rotorRates'] for value in rates)
            gates['fresh_FCU_disarmed_non_offboard'] = bool(fcu) and fcu[-1]['connected'] and not fcu[-1]['armed'] and fcu[-1]['mode'] not in ('', 'OFFBOARD')
            fresh_pid = receipt.get('freshPx4Pid')
            fresh_start = receipt.get('freshPx4StartTime')
            gates['FCU_history_fresh_process_proof'] = (bool(receipt.get('newGeneration')) and
                receipt['newGeneration'] != receipt.get('oldGeneration') and fresh_pid is not None and
                fresh_start is not None and proc_start(int(fresh_pid)) == str(fresh_start))
            # Requires watch evidence covering the whole operation, not before/after screenshots.
            if not args.before: raise RuntimeError('requires continuous watch evidence across owning reset')
            watch=json.loads(args.before.read_text())
            first = next((sample['A'] for sample in watch.get('samples', []) if sample.get('A')), None)
            gates['A_was_actually_moved_before_reset'] = first is not None and norm(
                [a-b for a,b in zip(first['position'], target)]) > .3
            for gate in ('clock_not_reset','clock_continues','clock_no_stall_over_2s','sibling_no_teleport'):
                gates[gate]=watch.get('gates',{}).get(gate) is True
        if args.phase == 'verify-source-loss':
            if not args.before: raise RuntimeError('requires pre-loss actual body observation')
            before=json.loads(args.before.read_text())['samples'][-1]['A']
            target=[initial[name] for name in ('x','y','z')]
            gates['source_loss_not_returned_to_initial'] = norm([a-b for a,b in zip(before['position'],target)])>.3 and norm([a-b for a,b in zip(samples[-1]['A']['position'],target)])>.3
            gates['source_loss_no_discontinuity'] = all(norm([y-x for x,y in zip(a['A']['position'],b['A']['position'])])<.5 for a,b in zip(samples,samples[1:]))
    except Exception as error:
        failure=str(error)
    result={'phase':args.phase,'spec':spec,
            'renderedSdfSha256':hashlib.sha256(Path(spec['renderedSdf']).read_bytes()).hexdigest(),
            'samples':samples,'clock':clocks,'fcu':fcu,'gates':gates,
            'failure':failure,'pass':failure is None and bool(gates) and all(gates.values()),
            'boundary':'actual domain observation, not production UI10 acceptance; no reset action issued'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    for subscription in subscriptions: subscription.unregister()
    print(json.dumps({'output':str(args.output),'gates':gates,'failure':failure,'pass':result['pass']}))
    return 0 if result['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
