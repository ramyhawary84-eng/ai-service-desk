#!/usr/bin/env python3
"""Offline checks for portable workflow integrity and publication hygiene."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors = []
workflows = sorted((ROOT / 'workflows').glob('*.json'))
if len(workflows) != 3:
    errors.append(f'Expected three workflows; found {len(workflows)}.')


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


for path in workflows:
    data = json.loads(path.read_text())
    names = [node['name'] for node in data['nodes']]
    if len(names) != len(set(names)):
        errors.append(f'{path.name}: duplicate node names.')
    if data.get('active') is not False:
        errors.append(f'{path.name}: workflow must be inactive.')
    if data.get('pinData'):
        errors.append(f'{path.name}: pinned execution data present.')
    for obj in walk(data):
        if 'credentials' in obj:
            errors.append(f'{path.name}: saved credential references present.')
    for source, ports in data.get('connections', {}).items():
        if source not in names:
            errors.append(f'{path.name}: missing source node {source!r}.')
        for outputs in ports.values():
            for connections in outputs:
                for edge in connections:
                    if edge['node'] not in names:
                        errors.append(f'{path.name}: missing destination {edge["node"]!r}.')
    serialized = json.dumps(data, ensure_ascii=False)
    for target in re.findall(r"\$\(['\"]([^'\"]+)['\"]\)", serialized):
        if target not in names:
            errors.append(f'{path.name}: expression references missing node {target!r}.')
    for node in data['nodes']:
        schema = node.get('parameters', {}).get('inputSchema')
        if isinstance(schema, str) and schema.lstrip().startswith('{'):
            try:
                json.loads(schema)
            except ValueError:
                errors.append(f'{path.name}: invalid schema JSON in {node["name"]}.')

for path in ROOT.rglob('*'):
    if not path.is_file() or any(part in {'.git', '__pycache__'} for part in path.parts):
        continue
    if path.name == 'config.json' and path.parent.name == 'frontend':
        # Local configuration is gitignored and intentionally differs per installation.
        continue
    if path.suffix.lower() in {'.sqlite', '.db', '.log', '.mp4', '.mov', '.pem', '.key'}:
        errors.append(f'Unpublishable file type: {path.relative_to(ROOT)}')
    try:
        text = path.read_text()
    except UnicodeError:
        continue
    patterns = {
        'OpenAI-style key': r'\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}',
        'GitHub-style token': r'\b(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}',
        'Slack-style token': r'\bxox[baprs]-[A-Za-z0-9-]{15,}',
        'JWT-like token': r'\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}',
        'Private key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    }
    for label, pattern in patterns.items():
        if re.search(pattern, text):
            errors.append(f'{path.relative_to(ROOT)}: possible {label}.')

for path in ROOT.rglob('*.md'):
    for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
        if '://' in target or target.startswith('#'):
            continue
        target = target.split('#', 1)[0]
        if target and not (path.parent / target).exists():
            errors.append(f'{path.relative_to(ROOT)}: missing linked file {target}.')

if errors:
    raise SystemExit('\n'.join(errors))
print(f'PASS: {len(workflows)} workflow graphs, JSON schemas, relative documentation links, and publication checks.')
print('This is an offline integrity check, not a live service-delivery test or exhaustive secret audit.')
