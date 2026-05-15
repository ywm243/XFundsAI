#!/usr/bin/env python3
"""Start SmartBI API server with Oracle Instant Client env vars."""
import subprocess, sys, os

os.chdir(os.path.expanduser("~/smart-bi"))
env = os.environ.copy()
ic_dir = os.path.expanduser("~/oracle/instantclient_21_12")
env["LD_LIBRARY_PATH"] = f"{ic_dir}:" + env.get("LD_LIBRARY_PATH", "")

log = open("/tmp/smartbi-api.log", "w")
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"],
    stdout=log, stderr=log, env=env,
)
print(proc.pid)
