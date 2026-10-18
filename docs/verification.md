# Verification and evidence

The original project was exercised through the employee frontend, n8n, Jira, Slack, Confluence, and Qdrant. Its narrated demo includes authentic screen recordings and executed workflow paths. The repository is a sanitized reproduction package, not a copy of the live databases or credentials.

## Checks repeated for publication

- **23 frontend adapter tests passed** using isolated simulated n8n responses.
- Workflow graph, named-node references, JSON/schema validity, inactive state, and publication-content checks are run by `scripts/validate_repository.py`.
- A repository CI workflow repeats the adapter and repository checks on supported GitHub events.

These checks do not execute an external AI provider or prove delivery to Jira/Slack in a new installation.

## Original demonstration coverage

| Area | Evidence |
| --- | --- |
| Conversation and clarification | Recorded frontend intake and workflow follow-up handling |
| P1 business impact | Payroll-blocking request, calculated priority, Jira Highest, engineer handoff |
| RAG | Confluence approval, ingestion workflow, Qdrant passages, versioned citations |
| Self-service | Edge Ctrl+0 guidance and Jira record through the eligible branch |
| Security | Unrequested MFA report, security branch, specialist-review ticket and Slack |
| No applicable knowledge | No-match response and technician handoff |
| Repeated submission | Existing Jira ticket reference returned |
| Human review | Rejected draft, completed monitor execution, Slack review decision |

Recorded green nodes show which steps executed; a main workflow waiting on a form is not equivalent to a finished execution. The ingestion and review-monitor recordings separately show their completed runs.

## Practical limits

- This is a completed educational proof of concept, not a production reliability or security certification.
- LLM/provider errors can interrupt an execution. Passing a demonstration does not establish a service-level availability guarantee.
- Jira fingerprint search is a time-window duplicate check, not atomic concurrent-request deduplication or semantic incident correlation.
- Label-based notification suppression reduces repeats; Slack post and Jira label update are not one atomic transaction.
- Approval of knowledge or an AI draft does not establish incident resolution.
- The small knowledge library and bounded Confluence/Jira searches need pagination and lifecycle/error handling for larger deployments.
- The local frontend's compatibility is tied to n8n's form protocol.

These boundaries explain what the demonstrated system establishes and what a production engineering phase would need to address.

