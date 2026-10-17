#!/usr/bin/env python3
import os
import subprocess
import sys
import tempfile
import random
import signal
import threading
import time
import xmlrpc.client

import yaml

import re
def validate_namespace(value):
    value = value[1:] if value.startswith('/') else value
    if len(value) > 128 or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:/[A-Za-z][A-Za-z0-9_]*)*', value):
        raise SystemExit('invalid ROS namespace')
    return value

# One rosparam process loads the plugin lists, the MAVROS config and the
# trusted settings. Every robot used to spawn eight rosparam interpreters in
# series before MAVROS started, 800 for a 100-robot fleet. The documents apply
# in the old order: each config file as `rosparam load` reads it, then the
# settings with `rosparam set` value semantics (an empty value is "").
def ros_ns_join(namespace, name):
    if name.startswith(("/", "~")) or not namespace:
        return name
    return namespace + name if namespace.endswith("/") else namespace + "/" + name
def ros_set_value(key, text):
    if text in ("", "''", '""'):
        return ""
    value = yaml.safe_load(text)
    if value is None:
        raise SystemExit("MAVROS parameter " + key + " must not be null")
    return value
class MasterTransport(xmlrpc.client.Transport):
    def make_connection(self, host):
        connection = super().make_connection(host)
        connection.timeout = 1.0
        return connection


def main(argv=None):
    executable, namespace, node_name, config_files, instance, *settings = sys.argv[1:] if argv is None else argv
    if not instance.isdecimal() or not 0 <= int(instance) <= 243:
        raise SystemExit("invalid SITL instance")
    instance = int(instance)
    namespace = validate_namespace(namespace)
    if not node_name:
        raise SystemExit("ROS node name is required")
    private_namespace = "/" + namespace + "/" + node_name
    parameter_documents = []
    for config_file in filter(None, config_files.split(",")):
        with open(config_file, "r", encoding="utf-8") as stream:
            for document in yaml.safe_load_all(stream):
                if document is None:
                    continue
                if not isinstance(document, dict):
                    raise SystemExit("MAVROS config documents must be mappings: " + config_file)
                document = dict(document)
                document_namespace = ros_ns_join(private_namespace, document.pop("_ns")) if "_ns" in document else private_namespace
                parameter_documents.append(dict(_ns=document_namespace, **document))
    overrides = {
        "fcu_url": f"udp://:{15000 + instance}@127.0.0.1:{15300 + instance}",
        "target_system_id": instance + 1,
        "target_component_id": 1,
    }
    for setting in settings:
        key, separator, value = setting.partition("=")
        if not separator or not key:
            raise SystemExit("invalid trusted ROS parameter setting " + repr(setting))
        if key in ("fcu_url", "target_system_id", "target_component_id"):
            raise SystemExit("SITL instance owns MAVROS parameter " + key)
        overrides[key] = ros_set_value(key, value)
    clock = os.environ.get("XGC_ROS_USE_SIM_TIME", "false").lower()
    if clock not in ("true", "false"):
        raise SystemExit("XGC_ROS_USE_SIM_TIME must be a boolean")
    overrides["use_sim_time"] = clock == "true"
    parameter_documents.append(dict(_ns=private_namespace, **overrides))
    stopping = threading.Event()
    child = None
    def stop(signum, frame):
        stopping.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    master = xmlrpc.client.ServerProxy(os.environ["ROS_MASTER_URI"], transport=MasterTransport())
    bound_identity = None
    ceiling, last_log, suppressed = 0.25, None, 0
    with tempfile.NamedTemporaryFile("w", prefix="mavros-parameters-", suffix=".yaml", encoding="utf-8") as parameter_file:
        yaml.safe_dump_all(parameter_documents, parameter_file, sort_keys=False)
        parameter_file.flush()
        try:
            while not stopping.is_set():
                if child is not None and child.poll() is not None:
                    return child.returncode
                try:
                    result = master.getPid("/mavros_launcher")
                    if result[0] != 1:
                        raise RuntimeError("master identity is unavailable")
                    run_id = master.getParam("/mavros_launcher", "/run_id")
                    identity = (result[2], run_id[2] if run_id[0] == 1 else "")
                    replaced = bound_identity is not None and (identity[0] != bound_identity[0] or
                        (identity[1] and bound_identity[1] and identity[1] != bound_identity[1]))
                    if replaced:
                        print("ROS master replaced; ending bound MAVROS", file=sys.stderr, flush=True)
                        return 1
                    if child is None:
                        # This launcher owns only its node's parameter bootstrap.
                        # The FCU is a data peer: MAVROS binds UDP and waits itself.
                        master.deleteParam("/mavros_launcher", private_namespace)
                        subprocess.run(["/opt/ros/noetic/bin/rosparam", "load", parameter_file.name, "/"], check=True, timeout=5)
                        arguments = [executable, "__name:=" + node_name, "__ns:=/" + namespace,
                                     "/use_sim_time:=" + private_namespace + "/use_sim_time"]
                        child = subprocess.Popen(arguments)
                        bound_identity = identity
                    elif identity[1] and not bound_identity[1]:
                        # roscore can publish /run_id after its socket is bound.
                        # Learning that first value is not a master replacement.
                        bound_identity = identity
                    ceiling, last_log, suppressed = 0.25, None, 0
                    stopping.wait(10)
                except (OSError, ValueError, RuntimeError, xmlrpc.client.Error, subprocess.SubprocessError) as error:
                    suppressed += 1
                    now = time.monotonic()
                    if last_log is None or now - last_log >= 10:
                        print("ROS master unavailable: %s (%d failed attempts since last summary)" %
                              (error, suppressed), file=sys.stderr, flush=True)
                        last_log, suppressed = now, 0
                    stopping.wait(random.uniform(0, ceiling))
                    ceiling = min(30, ceiling * 2)
        finally:
            if child is not None:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                child.wait()
            master.__exit__(None, None, None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
