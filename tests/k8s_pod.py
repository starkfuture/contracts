#!/usr/bin/env python3
"""Print a ConfigMap + Pod that run the official DocuSeal image with build/app copied over /app.
Same files the Dockerfile copies, so the test exercises the image's content without a registry push.
    python3 tests/k8s_pod.py <namespace> | kubectl --context stark-staging apply -f -
"""
import json, os, re, secrets, sys

NS = sys.argv[1]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.environ.get("APP_DIR") or os.path.join(ROOT, "build", "app")
IMAGE = re.search(r"^MIRROR=(\S+)$", open(os.path.join(ROOT, "UPSTREAM")).read(), re.M).group(1)
NAME = "docuseal-stark-test"

data, items = {}, []
for d, _, fs in os.walk(APP):
    for f in fs:
        rel = os.path.relpath(os.path.join(d, f), APP)
        key = rel.replace("/", "__")
        data[key] = open(os.path.join(d, f)).read()
        items.append({"key": key, "path": rel})

labels = {"app": NAME, "owner": "claude-docuseal-stark"}
cm = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": NAME, "namespace": NS, "labels": labels}, "data": data}
pod = {
    "apiVersion": "v1", "kind": "Pod",
    "metadata": {"name": NAME, "namespace": NS, "labels": labels},
    "spec": {
        "securityContext": {"runAsUser": 2000, "runAsGroup": 2000, "fsGroup": 2000, "runAsNonRoot": True},
        "containers": [{
            "name": "docuseal", "image": IMAGE,
            "command": ["sh", "-c", "cd /stark-overlay && for f in $(find -L . -path '*/..*' -prune -o -type f -print); do mkdir -p /app/$(dirname $f) && cp -L $f /app/$f; done && cd /app && exec bin/bundle exec puma -C config/puma.rb --dir /app"],
            "env": [{"name": "SECRET_KEY_BASE", "value": secrets.token_hex(64)},
                    {"name": "FORCE_SSL", "value": "false"},
                    {"name": "WORKDIR", "value": "/data/docuseal"}],
            "ports": [{"containerPort": 3000}],
            "volumeMounts": [{"name": "overlay", "mountPath": "/stark-overlay"},
                             {"name": "data", "mountPath": "/data/docuseal"}],
            "resources": {"requests": {"cpu": "200m", "memory": "768Mi"}, "limits": {"memory": "1536Mi"}},
            "readinessProbe": {"httpGet": {"path": "/up", "port": 3000}, "periodSeconds": 5, "failureThreshold": 60},
            "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
        }],
        "volumes": [{"name": "overlay", "configMap": {"name": NAME, "items": items}},
                    {"name": "data", "emptyDir": {}}],
        "nodeSelector": {"kubernetes.io/arch": "amd64"},
    },
}
print(json.dumps({"apiVersion": "v1", "kind": "List", "items": [cm, pod]}))
