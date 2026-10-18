# Inspectable prompts and schemas

These files are extracted from `workflows/01-ai-service-desk.json` for easier review. The workflow JSON remains the import source of truth.

- `triage-system.txt`: classify the request, identify security evidence, and ask only useful missing questions.
- `impact-and-urgency-system.txt`: assess supplied business impact, deadline evidence, and workaround adequacy without assigning the final priority.
- `resolution-system.txt`: assess knowledge applicability and draft supported guidance with citations.
- `triage-schema.json` and `resolution-schema.json`: the connected parser schemas from the supplied export.

When changing a model configuration, ensure the schema, structured parser, and prompt specify the same object shape. n8n may place a parsed result in an outer `output` field; that does not itself mean the model should add another `output` wrapper. Supply one JSON schema object, with no concatenated copies or Markdown fences. Test the full path after changing provider response formatting.

