# Set up your own demonstration

This repository contains the application and portable n8n templates. It does not contain the author's credentials, Jira issues, Qdrant data, n8n database, or browser sessions.

## 1. Prepare the services

- Python 3.10+ for the frontend; it uses only the standard library.
- A local n8n installation. The project reference environment used **n8n 2.40.5** in Docker. The frontend depends on the n8n form-response protocol, so check compatibility before using another release.
- OpenAI access for chat models and embeddings, with available API usage.
- Jira Cloud project and issue type, with permission to create issues and update labels.
- Confluence space containing the demo knowledge articles.
- Qdrant collection for embeddings.
- Slack app/connection authorized to post in an engineer channel. Add the app to the selected channel, including if it is private.

Use an isolated demo environment and fictional requests. Running the workflows will call external services and can create Jira tickets and Slack posts.

For a new local instance, `docker compose up -d` uses the optional `compose.yaml`, a persistent Docker volume, loopback port 5678, and a 2 GB container limit. Complete n8n's owner-account setup in the browser. Keep your existing Docker installation if it already hosts the project; do not start a second instance on the same port. This reference Compose file was prepared for the repository and was not used for a new live deployment during publication. Docker's overall memory allocation must also leave enough memory for macOS and the browser.

## 2. Import the templates

Import the three JSON files from `workflows/` into n8n. They are inactive by design. Preserve the node names: expressions reference them exactly.

The templates use the following placeholders. Replace them throughout the workflow JSON before importing, or edit every matching node afterward:

| Placeholder | Replace with |
| --- | --- |
| `https://your-site.atlassian.net` | Your Jira/Confluence site origin |
| `https://your-cluster.cloud.qdrant.io` | Your Qdrant endpoint |
| `YOUR_CONFLUENCE_SPACE_ID` | Numeric Confluence space ID, kept as a string in metadata |
| `YOUR_JIRA_PROJECT_KEY` | Jira project key, for example `DEMO` |
| `YOUR_JIRA_PROJECT_ID` | Jira project ID used by the ticket nodes |
| `YOUR_JIRA_ISSUE_TYPE_ID` | Issue type available in that project |
| `YOUR_SLACK_CHANNEL_ID` | Engineer channel ID |
| `REPLACE_WITH_FORM_ID` | The imported Employee Request production form ID/path |

Select your own project, issue type, priorities, and Slack destination in the nodes. Jira priority IDs are site-specific: verify **Map Jira Priority** and the ticket nodes rather than assuming IDs 1–4 represent the same names on every site.

The publication process removes saved credential references. Reconnect credentials in all applicable nodes:

| Credential | Nodes |
| --- | --- |
| OpenAI | Chat models and embedding sub-nodes in workflows 01 and 02 |
| Qdrant | Vector-store nodes and the HTTP request that removes prior article chunks |
| Jira Software Cloud | Ticket creation, duplicate search, review search/current-state fetch, and review-label update |
| Confluence Basic Auth | Get Confluence Knowledge Pages |
| Slack | Engineer notifications and Notify Review Decision |
| Form authentication, where configured | Employee Request |

Never paste API tokens into workflow expressions or commit them to Git. Store them in n8n's credential manager.

## 3. Prepare Qdrant

Use collection name **`it_service_desk_kb`** to match the templates, or update every reference consistently. The reference collection uses **1536 dimensions** and **Cosine** distance. Select an embedding model/output dimension that matches this configuration in both ingestion and retrieval.

Create keyword payload indexes for:

- `metadata.category`
- `metadata.space_id`
- `metadata.page_id`
- `metadata.knowledge_approval`

These match the collection filters and page-chunk removal. Qdrant strict-mode configurations may reject filters without the required indexes.

## 4. Prepare and ingest knowledge

Create Confluence pages using `knowledge/KB-001-vpn-password-change.md` and `knowledge/KB-002-edge-page-zoom.md`. Keep the metadata labels at the top exactly as shown. Enter the appropriate approval state after reviewing the content for your demonstration.

The HTML extraction and metadata normalization expect the article body, title, page ID, space ID, and version returned by Confluence. Update the configured space ID in both ingestion and retrieval.

Run **02 – Knowledge Ingestion** manually. Confirm the output passages retain the correct article ID, version, category, approval, automatic-response flag, and source URL. Confirm Qdrant contains the new points. KB-001 must remain `automatic_response_allowed: false`; KB-002 demonstrates `true`.

The current Confluence request fetches up to 100 pages, without full pagination. Use this small demo knowledge base; extend pagination and lifecycle handling before using a larger library.

## 5. Configure the employee workflow

Check the form field names and order:

```text
requester_email
summary
description
affected_scope
business_effect
workaround
needed_by
```

The frontend reads field labels/options from n8n but its adapter maps this seven-field order. Preserve it or update `INITIAL_KEYS` in `frontend/server.py`.

Confirm the model response schema, structured parser, and system message agree. Preserve the model/embedding connections. Do not use “continue on error” as a substitute for valid structured output.

Check every route reaches its intended employee completion page: existing request, self-service, technician review, or specialist review. A Slack message alone cannot return the Jira reference to the chat. Follow the [frontend completion-page checklist](frontend-connection.md) for the named nodes and paste-ready expressions.

Publish/activate the main workflow when its credentials and destinations are ready. Copy the Employee Request **production** form URL, not a temporary signed waiting-page URL.

## 6. Start the frontend

```sh
cp frontend/config.example.json frontend/config.json
```

Edit the local `frontend/config.json`:

```json
{
  "n8n_url": "http://localhost:5678",
  "form_path": "/form/REPLACE_WITH_FORM_ID",
  "workflow_url": "http://localhost:5678/workflow/REPLACE_WITH_WORKFLOW_ID",
  "jira_url": "https://your-site.atlassian.net",
  "port": 5680
}
```

Then run:

```sh
python3 frontend/server.py
```

Open **http://localhost:5680** in the same browser profile used to sign in to local n8n. In Connection settings, check the connection. If prompted, use employee sign-in and complete n8n's authentication/consent yourself. The adapter does not submit passwords or approve consent.

For a temporary test listener, use `python3 frontend/server.py --test-form` and start listening in n8n before submitting. Production form mode is more convenient for the walkthrough.

## 7. Review decisions and Slack

New reviewed drafts use `ai-review-pending`. After a technician reviews the draft, remove that label and apply exactly one of `ai-review-approved` or `ai-review-rejected`. Add the technician's explanation in Jira.

Run **03 – Technician Review Monitor** manually first. It fetches the current issue, verifies eligibility, posts the decision, and adds `ai-review-notified`. A later run should skip it. Publish its five-minute schedule only after this test.

This implementation uses labels for a demonstration review process. Label edit access is not a hardened approval authorization system. A later reversal after notification requires deliberate handling of the notification marker; it is not an event-sourced decision history.

## 8. Check the demonstration

Use the fictional requests in `examples/demo-requests.json` and the route-by-route checklist in [demo.md](demo.md). Keep the laptop awake and Docker running during the local demo. The public repository itself does not host a running support service.

