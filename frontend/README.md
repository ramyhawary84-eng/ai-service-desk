# Employee chat frontend

A buildless local UI for the n8n service-desk workflow. The Python adapter reads n8n form fields, collects answers, submits after explicit confirmation, presents follow-up questions, and returns the workflow's result.

## Run

Copy `config.example.json` to `config.json`, fill in your imported workflow and Jira site, then run `python3 server.py` from this directory. Open **http://localhost:5680**. See the repository [setup guide](../docs/setup.md).

## Implementation

- `dist/index.html`, `styles.css`, `app.js`: responsive chat, topic starters, request summary, editable answers, and session history.
- `server.py`: local HTTP server, n8n form adapter, restricted redirects, in-memory session handling, and response parsing.
- `test_server.py`: 23 isolated tests using simulated backend responses.

No additional LLM runs in this frontend. Triage, priority, knowledge retrieval, and delivery rules stay in n8n.

For portability, the publication copy obtains the permitted Jira-link origin from `config.json` through `/api/health`, rather than hard-coding the author's site. Personal account values are replaced in configuration and test fixtures.

## Data handling

The server binds to loopback and accepts the configured local n8n origin. It forwards the existing `n8n-auth` cookie only to local n8n. A bounded GET-only authorization flow retains per-conversation cookies in memory. Interactive sign-in and consent remain user actions in n8n.

Form tokens, OAuth codes, and signed waiting URLs are not exposed as chat responses. A changed n8n browser session invalidates retained form cookies. The server writes no request/conversation logs. Browser history uses tab-scoped session storage; server sessions expire after two hours or a restart.

This is a local demonstration adapter, not an internet-facing authentication service. It supports text, email, textarea, and select fields. Its protocol compatibility must be checked when n8n changes.

## Test

```sh
python3 -m unittest -v test_server.py
```

These tests never create live tickets, send Slack messages, or use an AI provider.

