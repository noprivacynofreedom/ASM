#!/bin/bash
# usage: run.sh MODE  -> starts fake swap + atlas, returns when ready
S=${E2E_DIR:-/tmp/atlas-e2e}
A=$(cd "$(dirname "$0")/../../src-tauri/resources/atlas" && pwd)
pkill -f fake_swap.py; pkill -f "atlas.*server.py"; sleep 1
rm -rf $S/data; mkdir -p $S/data; echo "$1" > $S/data/mode
echo '{"server_port":18090,"upstream_port":18080}' > $S/data/settings.json
python3 $S/fake_swap.py 18080 $S/data & 
cd $A && ATLAS_DATA_DIR=$S/data ATLAS_PORT=18090 python3 server.py > $S/atlas.log 2>&1 &
for i in $(seq 1 30); do curl -s localhost:18090/api/state >/dev/null && break; sleep 1; done
echo ready
