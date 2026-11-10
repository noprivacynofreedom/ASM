# Atlas Node Gateway Contract v0.2

The desktop client is deliberately a client of the commercial Atlas gateway. Do not expose the existing Atlas Chat localhost API as this service. All non-loopback traffic must use HTTPS.

## Identity and registration

1. `POST /v1/nodes/challenge`
   - Request: `{ "node_id": "<sha256-hex-of-ed25519-public-key>", "public_key_hex": "<32-byte-ed25519-public-key-hex>" }`
   - Response: `{ "challenge": "<cryptographically-random-single-use-nonce>", "expires_at_unix": 0 }`
   - Server stores challenge against the public key for at most 60 seconds, one use only.
2. `POST /v1/nodes/register`
   - Request: node_id, public_key_hex, challenge, signature_hex.
   - Signature is Ed25519 over the exact UTF-8 challenge bytes.
   - Server recomputes SHA-256(public key), checks challenge ownership/expiry/one-use, then issues a high-entropy revocable node token.
   - Response: `{ "node_token": "<opaque-secret>" }`.

## Signed node requests

Every authenticated POST uses bearer node token plus:

- `x-atlas-node-id`
- `x-atlas-timestamp` (Unix seconds)
- `x-atlas-signature` (Ed25519 signature hex)

Signed bytes are UTF-8:

`{timestamp}.{HTTP_METHOD}.{path}.{lowercase_hex_sha256_of_exact_compact_JSON_body}`

The server must enforce a narrow clock-skew window, one-time/replay protection for mutating operations, body-size limits, token revocation, node status and consent, per-node rate limits, and constant-time token comparison. JSON must be compactly serialized with lexicographically ordered object keys to match serde_json's canonical Value serialization used by the client.

## Node lifecycle and workloads

- `POST /v1/nodes/heartbeat` — signed device status and hardware capacity; heartbeat expiry marks a node unavailable.
- `POST /v1/workloads/claim` — signed claim request; returns HTTP 204 when no work is available or `{ "workload": <signed envelope> }`.
- Workload envelope fields: `workload_id`, `image`, `command`, `max_memory_mb`, `max_cpu_percent`, `expires_at_unix`, `nonce`, `signature_hex`.
- Workload signature is Ed25519 over compact lexicographically ordered JSON of all envelope fields except `signature_hex`, signed by the configured trusted scheduler key.
- `POST /v1/workloads/complete` — signed request carrying the node-signed execution receipt.

The scheduler must never send arbitrary host paths, mounts, host commands, secrets or network privileges. Images must be immutable SHA-256 digests and separately allowlisted by the device owner. Rejected, expired, untrusted or non-allowlisted jobs must never execute.

## Distributed inference

- `GET /v1/network/status` — public health/capacity summary only; no private node metadata.
- `POST /v1/inference` — signed, authenticated inference request. The platform chooses compatible online nodes based on model, VRAM/RAM, context size, quantization, queue depth, network latency and node consent. It returns a request/job identifier and a streamable result contract; the initial desktop client currently expects a JSON response. Add a streaming response contract before claiming production streaming support.

The scheduler should support whole-model placement first. Tensor/pipeline splitting across home PCs is a later capability because bandwidth and latency can make it slower than single-node inference.

## Contribution accounting

- `POST /v1/workloads/complete` stores a signed node assertion but must not immediately credit money.
- A verifier independently validates job assignment, nonce, time window, model/runtime, output or task-specific proof, resource limits and duplicate submission.
- `POST /v1/contributions/settlement` (server-side signed settlement) records accepted units, rate, adjustments, period, and verifier identity.
- A client must label locally signed receipts `EXECUTED_UNVERIFIED`. Only a platform-signed settlement response from a pinned trusted verifier key may be displayed as verified/earnings eligible.

A node signature is not proof of correct computation. GPU inference generally needs task-level validation, redundancy/spot checks or other verification before payouts. Do not describe self-reported GPU time as cryptographically proven work.

## Missing platform implementation

These endpoints, database tables, scheduler, inference router, independent verifier, settlement ledger, customer billing and payment processing are not implemented by the desktop package. They are the next server-side workstream. The desktop code does not silently emulate their success.
