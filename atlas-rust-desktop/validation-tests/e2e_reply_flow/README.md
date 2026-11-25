Browser check of the reply flow against a fake llama-swap (cloud only, not the PC).
`mkdir -p /tmp/atlas-e2e; ./run.sh ok; node page.js`  (modes: ok, empty_once, bad_once, empty_always, slow)
`./run.sh slow; node detach.js close|stop`: close = full reply saved into the chat, stop = partial reply, nothing continues.
Needs `playwright` for node (`NODE_PATH`) and ports 18080/18090 free.
