#!/usr/bin/env python3
"""Local conversational adapter for an existing n8n multi-page form.

No additional LLM, API key, workflow editing, or browser automation is used.
Form credentials, waiting URLs, and answers live only in this process's memory.
"""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit, parse_qsl, parse_qs
from urllib.request import Request, build_opener, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parent
DIST = ROOT / 'dist'
MAX_TEXT = 8000
SESSION_TTL = 7200
INITIAL_KEYS = ['requester_email', 'summary', 'description', 'affected_scope', 'business_effect', 'workaround', 'needed_by']
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


class SupportError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class AuthenticationRequired(SupportError):
    def __init__(self, message, auth_url):
        super().__init__(message, 401)
        self.auth_url = auth_url


def public_error(error):
    output = {'error': str(error)}
    if isinstance(error, AuthenticationRequired):
        output.update({'auth_required': True, 'auth_url': error.auth_url})
    return output


@dataclass
class Element:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def all(self, predicate):
        found = [self] if predicate(self) else []
        for child in self.children:
            if isinstance(child, Element):
                found.extend(child.all(predicate))
        return found

    def text(self):
        if self.tag in {'script', 'style', 'noscript'}:
            return ''
        if self.tag == 'br':
            return '\n'
        value = ''.join(child.text() if isinstance(child, Element) else child for child in self.children)
        if self.tag in {'p', 'div', 'section', 'li', 'h1', 'h2', 'h3', 'ol', 'ul'}:
            value = '\n' + value + '\n'
        return value


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Element('document')
        self.stack = [self.root]
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = Element(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def clean_text(value):
    value = re.sub(r'<br\s*/?>', '\n', html.unescape(str(value)), flags=re.I)
    value = re.sub(r'[ \t\r\f\v]+', ' ', value)
    value = '\n'.join(line.strip() for line in value.splitlines())
    return re.sub(r'\n{3,}', '\n\n', value).strip()


def parse_page(source):
    tree = Document(source).root
    forms = tree.all(lambda e: e.tag == 'form' and (e.attrs.get('id') == 'n8n-form' or e.attrs.get('name') == 'n8n-form'))
    forms = forms or tree.all(lambda e: e.tag == 'form')
    visible_form = next((f for f in forms if 'display: none' not in f.attrs.get('style', '') and 'display:none' not in f.attrs.get('style', '')), None)
    fields, hidden = [], {}
    if visible_form:
        labels = {e.attrs.get('for'): clean_text(e.text()) for e in visible_form.all(lambda e: e.tag == 'label' and 'for' in e.attrs)}
        for node in visible_form.all(lambda e: e.tag in {'input', 'select', 'textarea'}):
            name = node.attrs.get('name') or node.attrs.get('id')
            kind = node.attrs.get('type', 'text') if node.tag == 'input' else node.tag
            if not name or 'disabled' in node.attrs or kind in {'submit', 'button', 'reset'}:
                continue
            if kind == 'hidden':
                hidden[name] = node.attrs.get('value', '')
                continue
            if kind in {'file', 'checkbox', 'radio', 'password'}:
                raise SupportError('This form contains an unsupported field. Use the original n8n form for this request.', 422)
            label = labels.get(node.attrs.get('id'), name)
            options = []
            if node.tag == 'select':
                for option in node.all(lambda e: e.tag == 'option' and 'disabled' not in e.attrs):
                    text = clean_text(option.text())
                    value = option.attrs.get('value', text)
                    if value:
                        options.append({'label': text, 'value': value})
            default = clean_text(node.text()) if node.tag == 'textarea' else node.attrs.get('value', '')
            fields.append({'name': name, 'label': label.rstrip(' *'), 'type': kind,
                           'required': 'required' in node.attrs or 'form-required' in node.attrs.get('class', ''),
                           'options': options, 'default': default})
    titles = tree.all(lambda e: e.tag == 'h1')
    title = clean_text(titles[0].text()) if titles else ''
    token = re.search(r"(?:const|let|var)\s+authToken\s*=\s*(['\"])(.*?)\1", source)
    if fields:
        return {'kind': 'form', 'fields': fields, 'hidden': hidden, 'title': title,
                'auth_token': token.group(2) if token else ''}
    if tree.all(lambda e: e.tag == 'iframe'):
        # The native hosting shell may require the submitter to connect credentials.
        # Do not skip that screen or enable submission behind its gate.
        return {'kind': 'native_auth_shell'}
    # Never treat an n8n sign-in screen or a generic application shell as a result.
    if re.search(r'<title[^>]*>[^<]*(?:sign\s*in|log\s*in)', source, re.I):
        raise SupportError('Sign in to n8n at localhost:5678 in this Chrome profile, then check the connection again.', 401)
    containers = tree.all(lambda e: e.attrs.get('id') == 'submitted-content')
    if not containers:
        containers = tree.all(lambda e: e.tag == 'div' and 'form-header' in e.attrs.get('class', '').split())
    if not containers:
        containers = tree.all(lambda e: e.tag == 'body')
    text = clean_text('\n'.join(e.text() for e in containers)) if containers else ''
    if not title and not text:
        raise SupportError('The workflow did not return a readable employee response. Check its Form Ending nodes.', 502)
    if any(word in title.lower() for word in ['problem submitting', 'error', 'not found']):
        raise SupportError('n8n reported a problem processing the request. Check the workflow execution before submitting again.', 502)
    anchors = tree.all(lambda e: e.tag == 'a' and e.attrs.get('href', '').startswith('https://'))
    links = [{'url': e.attrs['href'], 'label': clean_text(e.text())} for e in anchors]
    return {'kind': 'completion', 'title': title, 'text': text, 'links': links}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class N8nClient:
    def __init__(self, config, cookie=''):
        self.base = config['n8n_url'].rstrip('/')
        self.cookie = cookie
        self.form_url = self.base + config['form_path']
        self.cookies = CookieJar()
        self.user_agent = 'ITAssist-Local/1.0'
        self.last_form_url = ''
        self.opener = build_opener(NoRedirect())

    def auth_required(self, message=None):
        return AuthenticationRequired(
            message or 'n8n needs you to sign in or approve this employee form. Open employee sign-in, complete the prompts in n8n, then check the connection again.',
            self.form_url,
        )

    def ensure_identity(self, cookie):
        # A conversation must not retain one user's form tokens after a session change.
        if cookie != self.cookie:
            self.cookies.clear()
            raise self.auth_required('Your n8n session changed. Sign in to n8n, then start a new conversation. Check Jira first if you submitted already.')

    def url(self, url, allow_auth=False):
        target = urljoin(self.base + '/', url)
        parts, base = urlsplit(target), urlsplit(self.base)
        if parts.username or parts.password or (parts.scheme, parts.hostname, parts.port) != (base.scheme, base.hostname, base.port):
            raise SupportError('The workflow returned an unexpected form destination. No request was sent there.', 502)
        if parts.path.startswith(('/signin', '/login')):
            raise self.auth_required()
        if allow_auth and parts.path in {'/oauth/authorize', '/oauth/consent'}:
            if parts.path == '/oauth/authorize':
                query = parse_qs(parts.query)
                expected = urlsplit(self.form_url)
                # Follow only the authorization request for this exact employee form.
                for name in ['redirect_uri', 'resource']:
                    values = query.get(name, [])
                    if len(values) != 1:
                        raise SupportError('n8n returned an incomplete form authorization request.', 502)
                    value = urlsplit(values[0])
                    if value.username or value.password or value.query or value.fragment or (value.scheme, value.hostname, value.port, value.path.rstrip('/')) != (expected.scheme, expected.hostname, expected.port, expected.path.rstrip('/')):
                        raise SupportError('The authorization request does not belong to this employee form.', 502)
                if query.get('response_type') != ['code'] or not query.get('state') or query.get('code_challenge_method') != ['S256'] or not query.get('code_challenge'):
                    raise SupportError('n8n returned an unsupported form authorization flow.', 502)
            return target
        if not parts.path.startswith(('/form/', '/form-test/', '/form-waiting/')):
            raise SupportError('The workflow returned an unsupported destination. Check the n8n form configuration.', 502)
        return target

    def request(self, url, fields=None, token=''):
        target = self.url(url)
        headers = {'Accept': 'application/json, text/html;q=0.9', 'User-Agent': self.user_agent}
        if token:
            headers['x-auth-token'] = token
        data = None
        if fields is not None:
            boundary = 'ITAssist' + uuid.uuid4().hex
            segments = []
            for key, value in fields.items():
                if not re.fullmatch(r'[\w.\-]{1,128}', key):
                    raise SupportError('The form returned an unsupported field name.', 502)
                segments.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'.encode(), str(value).encode('utf-8'), b'\r\n'])
            segments.append(f'--{boundary}--\r\n'.encode())
            data = b''.join(segments)
            headers['Content-Type'] = 'multipart/form-data; boundary=' + boundary
        auth_flow = False
        for _ in range(10):
            req = Request(target, data=data, headers=headers, method='POST' if data is not None else 'GET')
            self.cookies.add_cookie_header(req)
            cookie = req.get_header('Cookie', '')
            if self.cookie:
                cookie = self.cookie + ('; ' + cookie if cookie else '')
            if cookie:
                req.add_header('Cookie', cookie)
            try:
                with self.opener.open(req, timeout=90) as response:
                    self.cookies.extract_cookies(response, req)
                    if urlsplit(target).path in {'/oauth/authorize', '/oauth/consent'}:
                        # An HTML consent/sign-in screen requires the user's interaction.
                        # Never post approvals, submit credentials, or auto-accept a grant.
                        raise self.auth_required()
                    decoded = self.decode(response.read(2_000_001), response.headers)
                    if decoded.get('kind') == 'native_auth_shell':
                        raise self.auth_required('The native n8n form has a sign-in or credential-connection step. Open employee sign-in, complete that step in n8n, then return here.')
                    if decoded.get('kind') == 'form':
                        parts = urlsplit(target)
                        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in {'code', 'state', 'error', 'error_description'}]
                        self.last_form_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))
                    return decoded
            except HTTPError as error:
                self.cookies.extract_cookies(error, req)
                error.close()
                if error.code in {301, 302, 303, 307, 308}:
                    location = urljoin(target, error.headers.get('Location', ''))
                    route = urlsplit(location).path
                    if data is None and (auth_flow or route in {'/oauth/authorize', '/oauth/consent'}):
                        target = self.url(location, allow_auth=True)
                        auth_flow = True
                        continue
                    return {'redirectURL': self.url(location)}
                if error.code in {401, 403, 428}:
                    raise self.auth_required('n8n requires your sign-in, permission, or a connected credential. Open employee sign-in and complete that step in n8n.') from None
                if error.code == 404:
                    raise SupportError('The employee form is unavailable. Publish the main n8n workflow, or start its test listener when using a Test URL.', 503) from None
                if error.code in {409, 410}:
                    raise SupportError('This form page has expired or was already submitted. Check Jira before starting another request.', 409) from None
                raise SupportError(f'n8n returned HTTP {error.code}. Check the workflow execution before submitting again.', 502) from None
            except (URLError, TimeoutError, OSError):
                raise SupportError('Could not confirm a response from local n8n. Keep Docker and n8n running. If you submitted already, check Jira before retrying.', 503) from None
        raise SupportError('The n8n sign-in flow did not finish after ten redirects. Open the employee form in n8n to complete sign-in, then check again.', 502)

    @staticmethod
    def decode(raw, headers):
        if len(raw) > 2_000_000:
            raise SupportError('The workflow response was too large to display safely.', 502)
        text = raw.decode('utf-8', errors='replace').strip()
        try:
            decoded = json.loads(text)
            if isinstance(decoded, dict):
                return decoded
        except (ValueError, TypeError):
            pass
        if text in {'running', 'waiting', 'form-waiting', 'success', 'null', 'error', 'crashed', 'canceled', 'new'}:
            return {'execution_status': text}
        if not text:
            return {'empty': True}
        return parse_page(text)


def form_key(field, index, initial):
    if not initial:
        return field['name']
    if field['name'] in INITIAL_KEYS:
        return field['name']
    # The inspected Employee Request has these seven fields in this exact order.
    if index < len(INITIAL_KEYS):
        return INITIAL_KEYS[index]
    return field['name']


def validate_answer(question, value):
    if not isinstance(value, str) or len(value) > MAX_TEXT:
        raise SupportError('Please keep this answer under 8,000 characters.')
    value = value.strip()
    if question.get('required') and not value:
        raise SupportError('Please answer this question before continuing.')
    if question.get('type') == 'email' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
        raise SupportError('Please enter a complete email address, such as alex@example.com.')
    if question.get('options'):
        matches = [o['value'] for o in question['options'] if value.casefold() in {o['value'].casefold(), o['label'].casefold()}]
        if not matches:
            raise SupportError('Please choose one of the options shown above.')
        value = matches[0]
    return value


def make_result(page, jira_url):
    title, text = clean_text(page.get('title', '')), clean_text(page.get('text', ''))
    full = title + '\n' + text
    ticket = re.search(r'\bKAN-\d+\b', full)
    kind = 'duplicate' if 'already registered' in full.lower() else 'guidance' if any(term in full.lower() for term in ['support guidance', 'automated guidance']) else 'review'
    urls = re.findall(r'https://[^\s<>"\]]+', text)
    candidates = page.get('links', []) + [{'url': u.rstrip('),;'), 'label': ''} for u in urls]
    references, seen = [], set()
    for item in candidates:
        url = item['url']
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname not in {'your-site.atlassian.net', 'support.microsoft.com'}:
            continue
        if parts.hostname == 'your-site.atlassian.net' and not parts.path.startswith('/wiki/'):
            continue
        if url in seen:
            continue
        seen.add(url)
        article = re.search(r'KB[-+]?(\d+)', url)
        label = 'KB-' + article.group(1) if article else (item.get('label') or 'Knowledge reference')
        references.append({'url': url, 'label': label[:80]})
    if not ticket:
        kind = 'unconfirmed'
    return {'kind': kind, 'ticket_key': ticket.group(0) if ticket else None,
            'ticket_url': jira_url.rstrip('/') + '/browse/' + ticket.group(0) if ticket else None,
            'references': references, 'title': title, 'text': text}


@dataclass
class Conversation:
    id: str
    fields: list
    hidden: dict
    url: str
    token: str = ''
    answers: dict = field(default_factory=dict)
    overview: dict = field(default_factory=dict)
    phase: str = 'collecting'
    round: int = 0
    cursor: int = 0
    created: float = field(default_factory=time.monotonic)
    results: dict = field(default_factory=dict)
    waiting_url: str = ''
    client: object = field(default=None, repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def view(self, message=''):
        result = {'conversation_id': self.id, 'phase': self.phase, 'round': self.round,
                  'overview': dict(self.overview), 'message': message, 'connected': True}
        if self.phase in {'collecting', 'clarification'} and self.cursor < len(self.fields):
            result['question'] = self.fields[self.cursor]
        if self.phase == 'ready':
            result['review'] = [{**f, 'value': self.answers.get(f['name'], '')} for f in self.fields]
        return result

    def next_question(self):
        while self.cursor < len(self.fields) and self.fields[self.cursor]['name'] in self.answers:
            self.cursor += 1
        if self.cursor >= len(self.fields):
            self.phase = 'ready'
            return self.view('Thanks. Review these details, then send them to IT support.' if not self.round else 'Thanks. Review your follow-up answers, then send them for reassessment.')
        q = self.fields[self.cursor]
        key = q.get('key', q['name'])
        prompts = {
            'requester_email': 'What email address should IT use for this request?',
            'summary': 'What short title would you give this issue?',
            'description': 'What happened? Include the application, device, and any error message you see.',
            'affected_scope': 'Who is affected by this issue?',
            'business_effect': 'What work is affected, and what happens if it stays unavailable? Include any business deadline and why it matters.',
            'workaround': 'Can you continue the affected work using a temporary workaround?',
            'needed_by': 'When do you need service restored? This is your requested timing; IT will assess urgency from the business impact.'
        }
        return self.view(prompts.get(key, q['label']))


class SupportService:
    def __init__(self, config, client_factory=N8nClient):
        self.config = config
        self.sessions = {}
        self.sessions_lock = threading.Lock()
        self.client_factory = client_factory

    def client(self, cookie, user_agent=''):
        client = self.client_factory(self.config, cookie)
        if user_agent:
            client.user_agent = user_agent
        return client

    def check(self, cookie, user_agent=''):
        client = self.client(cookie, user_agent)
        page = client.request(self.config['form_path'])
        if page.get('redirectURL'):
            page = client.request(page['redirectURL'])
        if page.get('kind') != 'form' or len(page['fields']) != 7:
            raise SupportError('The expected seven-field Employee Request form was not returned. Check the configured form URL.', 503)
        return {'connected': True}

    def chat(self, payload, cookie, user_agent=''):
        session_id = payload.get('conversation_id')
        if not session_id:
            if payload.get('action', 'message') != 'message':
                raise SupportError('Start by describing your issue.')
            text = payload.get('message', '')
            if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
                raise SupportError('Describe the issue in 1–8,000 characters.')
            client = self.client(cookie, user_agent)
            page = client.request(self.config['form_path'])
            if page.get('redirectURL'):
                page = client.request(page['redirectURL'])
            if page.get('kind') != 'form' or len(page['fields']) != 7:
                raise SupportError('The employee intake form is unavailable or its fields changed. Check the workspace connection.', 503)
            with self.sessions_lock:
                now = time.monotonic()
                self.sessions = {sid: s for sid, s in self.sessions.items() if now - s.created < SESSION_TTL}
                if len(self.sessions) >= 100:
                    raise SupportError('This local demo has reached its active conversation limit. Restart it after completing current requests.', 503)
                s = Conversation(uuid.uuid4().hex, page['fields'], page.get('hidden', {}), self.config['form_path'], page.get('auth_token', ''))
                s.client = client
                s.url = getattr(client, 'last_form_url', '') or s.url
                self.sessions[s.id] = s
            for index, f in enumerate(s.fields):
                f['key'] = form_key(f, index, True)
                if f['key'] == 'description':
                    s.answers[f['name']] = text.strip()
                    s.overview['description'] = text.strip()
                if f['key'] == 'summary':
                    # A literal excerpt, not an invented AI summary. The employee can edit it.
                    s.answers[f['name']] = re.sub(r'\s+', ' ', text).strip()[:110]
            return s.next_question()

        with self.sessions_lock:
            s = self.sessions.get(session_id)
        if not s or time.monotonic() - s.created > SESSION_TTL:
            raise SupportError('This local conversation expired or the chat server restarted. Start a new conversation; check Jira first if you submitted already.', 410)
        if not s.lock.acquire(blocking=False):
            raise SupportError('This conversation is already processing a request. Please wait for its response.', 409)
        try:
            if s.client and hasattr(s.client, 'ensure_identity'):
                s.client.ensure_identity(cookie)
            message_id = payload.get('message_id')
            if not isinstance(message_id, str) or not re.fullmatch(r'[\w-]{1,80}', message_id):
                raise SupportError('A valid message identifier is required.')
            if message_id in s.results:
                return s.results[message_id]
            action = payload.get('action', 'message')
            if action == 'message':
                if s.phase not in {'collecting', 'clarification'}:
                    raise SupportError('Use the action shown in the conversation before sending another answer.', 409)
                q = s.fields[s.cursor]
                try:
                    answer = validate_answer(q, payload.get('message', ''))
                except SupportError as error:
                    return s.view(str(error))
                s.answers[q['name']] = answer
                if q.get('key') in INITIAL_KEYS:
                    s.overview[q['key']] = answer
                s.cursor += 1
                output = s.next_question()
            elif action == 'edit':
                if s.phase != 'ready':
                    raise SupportError('Details can be edited before submission.', 409)
                q = next((f for f in s.fields if f['name'] == payload.get('field')), None)
                if not q:
                    raise SupportError('Unknown request field.')
                value = validate_answer(q, payload.get('value', ''))
                s.answers[q['name']] = value
                if q.get('key') in INITIAL_KEYS:
                    s.overview[q['key']] = value
                output = s.view('Your detail has been updated. You can submit when ready.')
            elif action == 'submit':
                if s.phase != 'ready':
                    raise SupportError('This page was already submitted or is not ready. Do not submit again.', 409)
                # Mark before sending: a timeout must not cause an automatic duplicate POST.
                s.phase = 'waiting'
                client = s.client or self.client(cookie, user_agent)
                try:
                    response = client.request(s.url, {**s.hidden, **s.answers}, s.token)
                    output = self.resolve(s, response, client)
                except SupportError as error:
                    output = s.view('I could not confirm the result of that submission.')
                    output['notice'] = str(error) + ' The request may already exist; check Jira before starting again.'
                    if isinstance(error, AuthenticationRequired):
                        output.update({'auth_required': True, 'auth_url': error.auth_url})
            elif action == 'resume':
                if s.phase != 'waiting':
                    raise SupportError('There is no pending response to check.', 409)
                if not s.waiting_url:
                    output = s.view('The workflow did not provide a response address. Please check Jira before starting a new request.')
                    output['notice'] = 'The previous submission is unconfirmed. This action did not submit it again.'
                else:
                    output = self.resolve(s, {'formWaitingUrl': s.waiting_url}, s.client or self.client(cookie, user_agent))
            else:
                raise SupportError('Unsupported conversation action.')
            s.results[message_id] = output
            if len(s.results) > 80:
                del s.results[next(iter(s.results))]
            return output
        finally:
            s.lock.release()

    def resolve(self, s, response, client):
        deadline = time.monotonic() + 105
        for _ in range(140):
            if response.get('kind') == 'form':
                if s.round >= 1:
                    s.phase = 'waiting'
                    output = s.view('The workflow requested another clarification page. Please ask IT to review the request rather than repeating the questions.')
                    output['notice'] = 'The agreed one-round clarification limit was reached.'
                    return output
                s.round += 1
                s.fields, s.hidden = response['fields'], response.get('hidden', {})
                s.token = response.get('auth_token') or s.token
                s.answers, s.cursor, s.phase = {}, 0, 'clarification'
                output = s.next_question()
                output['message'] = 'A few more details will help IT assess this correctly.\n\n' + output['message']
                return output
            if response.get('kind') == 'completion' or 'formSubmittedText' in response:
                page = response if response.get('kind') else {'title': 'Request update', 'text': response['formSubmittedText'], 'links': []}
                result = make_result(page, self.config['jira_url'])
                s.phase = 'complete'
                output = s.view(result['text'] or result['title'])
                output['result'] = result
                return output
            next_url = response.get('formWaitingUrl') or response.get('redirectURL')
            if next_url:
                s.waiting_url = client.url(next_url)
                s.url = s.waiting_url
                if response.get('redirectURL'):
                    response = client.request(s.waiting_url)
                    continue
            status = response.get('execution_status')
            if status in {'error', 'crashed', 'canceled'}:
                raise SupportError('The n8n execution did not finish successfully. Check its execution log and Jira before retrying.', 502)
            if status == 'form-waiting':
                response = client.request(s.waiting_url)
                continue
            if status == 'success':
                s.phase = 'complete'
                output = s.view('The workflow finished, but it did not return an employee confirmation. Please check with IT before submitting the same request again.')
                output['result'] = {'kind': 'unconfirmed', 'ticket_key': None, 'ticket_url': None, 'references': []}
                return output
            if not s.waiting_url:
                s.phase = 'waiting'
                output = s.view('Your submission was sent, but the workflow did not return a confirmation page.')
                output['notice'] = 'Check Jira before resubmitting. The workflow may need a Form Ending on this branch.'
                return output
            if time.monotonic() >= deadline:
                s.phase = 'waiting'
                output = s.view('The workflow is still processing. You can check for its response without submitting again.')
                output['notice'] = 'The request is pending; checking again will not create another submission.'
                return output
            parts = urlsplit(s.waiting_url)
            status_url = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/') + '/n8n-execution-status', parts.query, ''))
            time.sleep(0.75)
            response = client.request(status_url)
        raise SupportError('The workflow returned too many redirects or status changes. Check its execution before retrying.', 502)


def forwarded_cookie(raw):
    try:
        cookies = SimpleCookie()
        cookies.load(raw or '')
        # Forward only the existing n8n session, only to the configured loopback n8n.
        return '; '.join(f'{name}={cookies[name].value}' for name in ['n8n-auth'] if name in cookies)
    except Exception:
        return ''


class Handler(BaseHTTPRequestHandler):
    server_version = 'ITAssistLocal/1.0'

    def log_message(self, *_args):
        pass  # Do not write answers, cookies, signatures, or conversation URLs to disk.

    def respond(self, status, body, content_type='application/json; charset=utf-8'):
        raw = json.dumps(body).encode() if content_type.startswith('application/json') else body
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def check_host(self):
        host = self.headers.get('Host', '')
        if host not in {f'localhost:{self.server.server_port}', f'127.0.0.1:{self.server.server_port}'}:
            raise SupportError('Use the local IT Assist address.', 403)
        origin = self.headers.get('Origin')
        if origin and origin not in {f'http://localhost:{self.server.server_port}', f'http://127.0.0.1:{self.server.server_port}'}:
            raise SupportError('Cross-site requests are not allowed.', 403)
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise SupportError('Cross-site requests are not allowed.', 403)

    def do_GET(self):
        try:
            self.check_host()
            path = urlsplit(self.path).path
            service = self.server.service
            if path == '/api/health':
                return self.respond(200, {'status': 'ready', 'form_url': service.config['n8n_url'] + service.config['form_path'], 'workflow_url': service.config['workflow_url'], 'jira_url': service.config['jira_url'], 'live_connection_checked': False})
            if path == '/api/check':
                return self.respond(200, service.check(forwarded_cookie(self.headers.get('Cookie')), self.headers.get('User-Agent', '')))
            assets = {'/': 'index.html', '/index.html': 'index.html', '/app.js': 'app.js', '/styles.css': 'styles.css', '/mark.svg': 'mark.svg'}
            if path not in assets:
                return self.respond(404, {'error': 'Not found.'})
            file = DIST / assets[path]
            mime = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
            return self.respond(200, file.read_bytes(), mime + ('; charset=utf-8' if mime.startswith('text/') or mime in {'application/javascript'} else ''))
        except SupportError as error:
            self.respond(error.status, public_error(error))
        except Exception:
            self.respond(500, {'error': 'The local support server could not complete the request.'})

    def do_POST(self):
        try:
            self.check_host()
            if urlsplit(self.path).path != '/api/chat':
                return self.respond(404, {'error': 'Not found.'})
            if self.headers.get_content_type() != 'application/json':
                raise SupportError('JSON requests are required.', 415)
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                raise SupportError('Invalid request length.') from None
            if size < 1 or size > 60000:
                raise SupportError('The request is empty or too large.', 413)
            try:
                payload = json.loads(self.rfile.read(size))
            except (ValueError, UnicodeError):
                raise SupportError('The request must contain valid JSON.') from None
            if not isinstance(payload, dict):
                raise SupportError('A JSON object is required.')
            output = self.server.service.chat(payload, forwarded_cookie(self.headers.get('Cookie')), self.headers.get('User-Agent', ''))
            self.respond(200, output)
        except SupportError as error:
            self.respond(error.status, public_error(error))
        except Exception:
            self.respond(500, {'error': 'The local support server could not complete this step. If you submitted already, check Jira before trying again.'})


def load_config():
    config = json.loads((ROOT / 'config.json').read_text())
    parts = urlsplit(config['n8n_url'])
    if parts.scheme != 'http' or parts.hostname not in {'localhost', '127.0.0.1'} or parts.username or parts.password:
        raise SystemExit('n8n_url must be a credential-free local HTTP address.')
    if not re.fullmatch(r'/form(?:-test)?/[\w-]+', config['form_path']):
        raise SystemExit('form_path must be an n8n production or test form path.')
    return config


def main():
    config = load_config()
    parser = argparse.ArgumentParser(description='Run the local IT Assist chat frontend.')
    parser.add_argument('--port', type=int, default=config['port'])
    parser.add_argument('--test-form', action='store_true', help='Use the existing n8n test form listener instead of the production URL.')
    args = parser.parse_args()
    if args.test_form:
        config['form_path'] = config['form_path'].replace('/form/', '/form-test/')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    server.service = SupportService(config)
    print(f'IT Assist is ready at http://localhost:{server.server_port}', flush=True)
    print('Local only. No live n8n request is sent until you check the connection or start a conversation.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
