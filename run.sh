#!/bin/bash
export LD_LIBRARY_PATH="$HOME/oracle/instantclient_21_12:$LD_LIBRARY_PATH"
cd "$HOME/smart-bi"
exec python3 -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
