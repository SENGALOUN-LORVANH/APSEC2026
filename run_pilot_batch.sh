#!/bin/bash
cd /work/experiment_v2
export QC_WORKSPACES=/data/qc_workspaces
export JDK8=/usr/lib/jvm/java-8-openjdk-amd64
export JDK21=/usr/lib/jvm/java-21-openjdk-amd64
python src/run_pilot.py
