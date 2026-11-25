#!/usr/bin/env python3
"""Print a ConfigMap + Pod that run the official DocuSeal image with build/app copied over /app, on a
throwaway Postgres (the image staging DocuSeal's own database runs). Same files the Dockerfile copies,
so the test exercises the image's content without a registry push.
    python3 tests/k8s_pod.py <namespace> | kubectl --context stark-staging apply -f -

Before copying, the pod checks the image's own copies of the files in PINS: the image must contain
exactly the upstream source the patches were made against, or the pod refuses to start.
APP_DIR=<dir> runs other files instead of build/app (tests/baseline.sh).
"""
import json, os, re, secrets, sys

NS = sys.argv[1]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.environ.get("APP_DIR") or os.path.join(ROOT, "build", "app")
IMAGE = re.search(r"^MIRROR=(\S+)$", open(os.path.join(ROOT, "UPSTREAM")).read(), re.M).group(1)
POSTGRES = "ghcr.io/zalando/spilo-17:4.0-p2"
NAME = "docuseal-stark-test"

data = {"PINS": open(os.path.join(ROOT, "PINS")).read()}
items = [{"key": "PINS", "path": "PINS"}]
for d, _, fs in os.walk(APP):
    for f in fs:
        rel = os.path.relpath(os.path.join(d, f), APP)
        key = rel.replace("/", "__")
        data[key] = open(os.path.join(d, f)).read()
        items.append({"key": key, "path": f"app/{rel}"})

start_app = " && ".join([
    # the image must be the pinned upstream source
    "cd /app && sha256sum -c -s /stark/PINS || { echo 'image does not match PINS'; exit 1; }",
    "cd /stark/app && for f in $(find -L . -path '*/..*' -prune -o -type f -print); do mkdir -p /app/$(dirname $f) && cp -L $f /app/$f; done",
    "until nc -z 127.0.0.1 5432; do sleep 1; done",
    "cd /app && exec bin/bundle exec puma -C config/puma.rb --dir /app",
])
start_db = ("B=/usr/lib/postgresql/17/bin; $B/initdb -D /pgdata/d -U postgres --auth=trust >/dev/null && "
            "{ $B/postgres -D /pgdata/d -k /tmp -c listen_addresses=127.0.0.1 & P=$!; "
            "wait $P; }")

labels = {"app": NAME, "owner": "claude-docuseal-stark"}
cm = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": NAME, "namespace": NS, "labels": labels}, "data": data}
secure = {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}}
pod = {
    "apiVersion": "v1", "kind": "Pod",
    "metadata": {"name": NAME, "namespace": NS, "labels": labels},
    "spec": {
        "securityContext": {"runAsUser": 2000, "runAsGroup": 2000, "fsGroup": 2000, "runAsNonRoot": True},
        "containers": [
            {"name": "docuseal", "image": IMAGE, "command": ["sh", "-c", start_app],
             "env": [{"name": "SECRET_KEY_BASE", "value": secrets.token_hex(64)},
                     {"name": "FORCE_SSL", "value": "false"},
                     {"name": "WORKDIR", "value": "/data/docuseal"},
                     {"name": "DATABASE_URL", "value": "postgresql://postgres@127.0.0.1:5432/postgres"}],
             "ports": [{"containerPort": 3000}],
             "volumeMounts": [{"name": "overlay", "mountPath": "/stark"}, {"name": "data", "mountPath": "/data/docuseal"}],
             "resources": {"requests": {"cpu": "200m", "memory": "768Mi"}, "limits": {"memory": "1536Mi"}},
             "readinessProbe": {"httpGet": {"path": "/up", "port": 3000}, "periodSeconds": 5, "failureThreshold": 60},
             "securityContext": secure},
            {"name": "postgres", "image": POSTGRES, "command": ["sh", "-c", start_db],
             "volumeMounts": [{"name": "pgdata", "mountPath": "/pgdata"}],
             "resources": {"requests": {"cpu": "100m", "memory": "256Mi"}, "limits": {"memory": "512Mi"}},
             "securityContext": dict(secure, runAsUser=101)},  # the image's postgres user
        ],
        "volumes": [{"name": "overlay", "configMap": {"name": NAME, "items": items}},
                    {"name": "data", "emptyDir": {}}, {"name": "pgdata", "emptyDir": {}}],
        "nodeSelector": {"kubernetes.io/arch": "amd64"},
    },
}
print(json.dumps({"apiVersion": "v1", "kind": "List", "items": [cm, pod]}))
