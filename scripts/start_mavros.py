#!/usr/bin/env python3
import os
import subprocess
import sys
import tempfile
import xmlrpc.client

import yaml

executable, namespace, node_name, config_files, *settings = sys.argv[1:]
import re
def validate_namespace(value):
    value = value[1:] if value.startswith('/') else value
    if len(value) > 128 or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:/[A-Za-z][A-Za-z0-9_]*)*', value):
        raise SystemExit('invalid ROS namespace')
    return value

namespace = validate_namespace(namespace)

namespace = namespace.strip("/")
if not node_name:
    raise SystemExit("ROS node name is required")
private_namespace = "/" + "/".join(filter(None, (namespace, node_name)))
rosparam = "/opt/ros/noetic/bin/rosparam"

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
overrides = {}
for setting in settings:
    key, separator, value = setting.partition("=")
    if not separator or not key:
        raise SystemExit("invalid trusted ROS parameter setting " + repr(setting))
    overrides[key] = ros_set_value(key, value)
parameter_documents.append(dict(_ns=private_namespace, **overrides))
# `rosparam delete` of an absent namespace failed and was ignored; a master
# that does not answer fails the load below instead.
try:
    xmlrpc.client.ServerProxy(os.environ.get("ROS_MASTER_URI", "")).deleteParam("/mavros_launcher", private_namespace)
except (OSError, ValueError, xmlrpc.client.Error):
    pass
with tempfile.NamedTemporaryFile("w", prefix="mavros-parameters-", suffix=".yaml", encoding="utf-8") as parameter_file:
    yaml.safe_dump_all(parameter_documents, parameter_file, sort_keys=False)
    parameter_file.flush()
    subprocess.run([rosparam, "load", parameter_file.name, "/"], check=True)
arguments = [executable, "__name:=" + node_name]
if namespace:
    arguments.append("__ns:=/" + namespace)
os.execv(executable, arguments)
