# Laptop setup (compute sharing)

Verify the llama-swap version first: `llama-swap --help` (the `--listen` flag is needed).

1. Copy `laptop-llama-swap.config.yaml` to the laptop. Replace every path.
2. Open PowerShell on the laptop. Start llama-swap for the home network:
   `llama-swap.exe --config C:\atlas\llama-swap\config.yaml --listen 0.0.0.0:8080`
3. Open the firewall for the private (home) profile only. Run PowerShell as Administrator:
   `New-NetFirewallRule -DisplayName "Atlas llama-swap (home only)" -Direction Inbound -Protocol TCP -LocalPort 8080 -Profile Private -Action Allow`
   Set the laptop network to "Private". Never use the Public profile. Never forward the port on your router.
4. Find the laptop address: `ipconfig` (IPv4 Address, for example 192.168.1.50).
5. On the PC, open Atlas, tab ATLAS NODE, section "Compute sharing". Enter `http://<laptop address>:8080`, press "Test connection", then "Save machine".
6. Chat with the model alias that the laptop reports (for example `laptop-7b`). The reply shows "answered by: Laptop".

Only the model port is open. The Atlas Chat API (127.0.0.1:8090) stays on its own machine.
