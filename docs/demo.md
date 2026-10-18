# Demo walkthrough

The final presentation pairs a male AI presenter with authentic project recordings. Each visual section is tied to its corresponding narration, including request input, executed workflow paths, decision outputs, Jira, and Slack.

The original recordings were captured on 18 October 2026. Use the examples in this repository to repeat the journeys in your own environment; ticket keys and timestamps will differ.

## Suggested walkthrough

| Segment | What to show | What it proves |
| --- | --- | --- |
| Business case and architecture | Employee-to-IT journey and connected services | Why selective automation is useful |
| Conversation | Chat intake, editable summary, useful follow-up | Structured context collected through a guided experience |
| VPN/payroll | Business impact, executed main path, P1 output, ticket, Slack | Business consequences determine priority |
| Knowledge source | Confluence KB-001 and KB-002 metadata | Approval and automatic-delivery permission are different |
| Ingestion | Completed ingestion path and stored passage metadata | Approved source content becomes retrievable knowledge |
| Retrieval | Returned passages, context, draft, source version | The draft is grounded in identifiable source material |
| Edge self-service | Eligible branch, guidance, Jira ticket | Narrow routine requests do not require approval every time |
| Security | Unrequested MFA message, security true branch, ticket, Slack | Reported security evidence changes the route |
| No match | Knowledge outcome, review route, ticket | The assistant does not invent unsupported steps |
| Duplicate | Identical repeat and the same ticket reference | Repeated submission is recognized within the configured window |
| Technician decision | Rejection, completed monitor path, node output, Slack | Human review decisions are communicated and tracked |

## Repeatable test inputs

Use `examples/demo-requests.json`. The employee is fictional. Do not use real passwords, authentication codes, sensitive personnel details, or production incidents.

1. Run the Edge case. Expect low impact/urgency and applicable KB-002 guidance if every eligibility check passes.
2. Run VPN payroll. Expect P1 / Highest with reviewed KB-001 draft and engineer notification.
3. Run security MFA. Expect specialist review and no ordinary self-service instructions.
4. Run no-knowledge hardware. Expect technician assessment if no applicable article is available.
5. Repeat exactly one submitted request within 30 minutes. Expect its existing ticket key.
6. Review a draft in Jira and apply one decision label. Run the monitor and verify Slack, then run again and verify the ticket is skipped.

The presentation demonstrates proof-of-concept outcomes; it does not quantify organizational savings. The original final video is maintained separately from source control to keep this repository small.

