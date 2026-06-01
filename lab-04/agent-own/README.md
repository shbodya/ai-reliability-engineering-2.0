# own-agent — A2A summarize agent

Minimal A2A v1.0 agent. Skill: `summarize` (char/word/line counts + first sentence).

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py    # listens on :9000
```

## Verify

Agent Card (well-known URI):
```bash
curl -s http://localhost:9000/.well-known/agent-card.json | jq .
```

Send task via JSON-RPC 2.0 (note: `A2A-Version: 1.0` header required):
```bash
curl -s -X POST http://localhost:9000/a2a/jsonrpc/ \
  -H 'Content-Type: application/json' \
  -H 'A2A-Version: 1.0' \
  -d '{
    "jsonrpc":"2.0","id":"1","method":"SendMessage",
    "params":{"message":{
      "messageId":"m-1","role":"ROLE_USER",
      "parts":[{"text":"Hello world. Second sentence here."}]
    }}
  }' | jq .
```

## Docker

```bash
docker build -t own-agent:0.1.0 .
docker run --rm -p 9000:9000 own-agent:0.1.0
```
