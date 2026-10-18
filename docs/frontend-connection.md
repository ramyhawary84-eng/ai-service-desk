# Return existing workflow outcomes to the chat

After importing, copy the Employee Request production URL. Its form is:

`http://localhost:5678/form/REPLACE_WITH_FORM_ID`

Keep **n8n User Auth** enabled. No webhook conversion, duplicate agent, or new credential is needed. The frontend uses the form's existing HTTP contract. The inspected review and escalation branches ended at Slack, and the duplicate True output had no ending connected. Add the following response pages in the n8n editor. If an equivalent page was added since that inspection, update or reuse it instead of adding a second ending.

All three are **n8n Form** nodes with:

- **Page Type:** Form Ending
- **On n8n Form Submission:** Show Completion Screen

## 1. Technician review acknowledgement

Name: **Return Review to Chat**

Connection: **Notify Engineers → Return Review to Chat**

Completion Title: **Request registered**

Completion Message → Expression:

```javascript
{{ (() => {
  const key = $('Create Review Ticket').first().json.key;
  const review = $('Prepare Technician Review').first().json.review_package;
  return [
    'Your request is registered as ' + key + '.',
    'Assessed priority: ' + review.priority + '.',
    'This request requires technician review. The IT team has been notified.',
    'A technician will review the details and contact you. Please quote ' + key + ' when following up.',
    'Your issue has not been confirmed resolved.'
  ].join('<br><br>');
})() }}
```

## 2. Security or incomplete-triage acknowledgement

Name: **Return Escalation to Chat**

Connection: **Notify Engineers1 → Return Escalation to Chat**

Use the actual Slack-node name if you renamed it to Notify Escalation.

Completion Title: **Request registered for specialist review**

Completion Message → Expression:

```javascript
{{ (() => {
  const key = $('Create Escalation Ticket').first().json.key;
  const security = $('Mark for Security Review').isExecuted;
  return [
    'Your request is registered as ' + key + '.',
    security
      ? 'The reported security concern requires specialist review. This does not confirm that your account is compromised.'
      : 'Some information still needs technician assessment.',
    'The IT team has been notified. Priority assessment is pending.',
    'Please quote ' + key + ' when contacting IT.',
    'Your issue has not been confirmed resolved.'
  ].join('<br><br>');
})() }}
```

## 3. Duplicate acknowledgement

Name: **Return Existing Request to Chat**

Connection: **Existing Request Found — True → Return Existing Request to Chat**

Completion Title: **Request already registered**

Completion Message → Expression:

```javascript
{{ 'An identical request was registered within the last 30 minutes as ' +
$json.issues[0].key +
'. Please quote that ticket when contacting IT. No additional ticket or Slack notification was created for this submission.' }}
```

Keep **Existing Request Found — False → Restore Request → Prepare Request**.

## Existing endings

Keep **Create Self-Service Ticket → Show Self-Service Guidance** and the existing priority-review **Create an issue → Form**. The chat reads their existing messages and citations.

## Make the connection available

Save and publish **01 – AI Service Desk MVP**. In the frontend, check the connection, then manually test the Edge zoom journey. That real submission will use OpenAI, create a Jira ticket unless detected as a duplicate, and may notify Slack according to the workflow policy.

The frontend build does not itself publish, edit, or execute this n8n workflow. Its adapter tests use simulated responses only.
