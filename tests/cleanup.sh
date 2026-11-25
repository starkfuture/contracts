#!/bin/bash
# Removes the throwaway test pod and its ConfigMap. Usage: tests/cleanup.sh <sandbox-namespace>
kubectl --context stark-staging -n "$1" delete pod,configmap -l owner=claude-docuseal-stark
