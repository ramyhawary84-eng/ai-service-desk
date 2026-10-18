"""Adapter checks with simulated n8n responses; never call real services."""
import json
import unittest
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit, parse_qs
from unittest.mock import patch

from server import (SupportError, AuthenticationRequired, N8nClient, SupportService,
                    forwarded_cookie, make_result, parse_page, validate_answer, public_error)


CONFIG = {'n8n_url': 'http://localhost:5678', 'form_path': '/form/example',
          'jira_url': 'https://your-site.atlassian.net'}


def form_html():
    return '''<html><title>Employee support</title><body>
    <form id="n8n-form"><h1>IT Support</h1>
    <label for="field-0">Your email</label><input id="field-0" name="field-0" type="email" class="form-required">
    <label for="field-1">Summary</label><input id="field-1" name="field-1" class="form-required">
    <label for="field-2">What happened?</label><textarea id="field-2" name="field-2" class="form-required"></textarea>
    <label for="field-3">Who is affected?</label><select id="field-3" name="field-3"><option disabled value="">Choose</option><option>Only me</option><option>My team</option></select>
    <label for="field-4">Business activity</label><textarea id="field-4" name="field-4"></textarea>
    <label for="field-5">Workaround</label><select id="field-5" name="field-5"><option>Yes</option><option>No</option></select>
    <label for="field-6">Needed by</label><select id="field-6" name="field-6"><option>Today</option><option>Within 1 hour</option></select>
    <input type="hidden" name="context" value="preserve me">
    </form><div id="submitted-form" style="display: none"><h1>Form Submitted</h1></div>
    <script>const authToken = 'example-not-a-real-secret';</script></body></html>'''


COMPLETION = '''<html><body><div class="card"><div class="form-header">
<h1>Your support guidance</h1><p>Request registered: KAN-99<br><br>
Select the affected Edge tab. Press Ctrl + 0. [KB-002]<br>
https://your-site.atlassian.net/wiki/spaces/IS/pages/123456/KB-002<br>
Your issue has not been confirmed resolved.</p></div></div></body></html>'''


class FakeClient:
    def __init__(self, factory):
        self.factory = factory

    def url(self, value):
        return N8nClient(CONFIG).url(value)

    def request(self, url, fields=None, token=''):
        self.factory.calls.append((url, fields, token))
        if fields is not None:
            response = self.factory.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        if '/n8n-execution-status' in url:
            return {'execution_status': 'form-waiting'}
        if '/form-waiting/' in url:
            return self.factory.pages.pop(0)
        return parse_page(form_html())


class Factory:
    def __init__(self, responses=None, pages=None):
        self.calls = []
        self.responses = list(responses or [parse_page(COMPLETION)])
        self.pages = list(pages or [])

    def __call__(self, config, cookie):
        return FakeClient(self)


class MockResponse:
    def __init__(self, body, cookies=()):
        self.body = body.encode()
        self.headers = Message()
        for cookie in cookies:
            self.headers.add_header('Set-Cookie', cookie)

    def info(self):
        return self.headers

    def read(self, limit):
        return self.body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass


class OAuthTransport:
    """In-memory HTTP protocol double. No browser or socket is opened."""
    def __init__(self, mode='success'):
        self.mode, self.calls = mode, []

    def redirect(self, request, location, cookies=()):
        headers = Message()
        headers['Location'] = location
        for cookie in cookies:
            headers.add_header('Set-Cookie', cookie)
        raise HTTPError(request.full_url, 302, 'Found', headers, BytesIO())

    def open(self, request, timeout=90):
        self.calls.append(request)
        parts = urlsplit(request.full_url)
        query = parse_qs(parts.query)
        base = CONFIG['n8n_url']
        resource = base + CONFIG['form_path']
        cookie = request.get_header('Cookie', '')
        if parts.path == '/form/example' and 'code' in query:
            return self.redirect(request, resource, ['n8n-form-oauth=one-hop-example; Path=/form/example; HttpOnly'])
        if parts.path == '/form/example':
            if request.get_method() == 'POST':
                return MockResponse(COMPLETION)
            if 'n8n-form-oauth=one-hop-example' in cookie:
                return MockResponse(form_html(), ['n8n-form-auth-wf-example=page-example; Path=/form-waiting; HttpOnly'])
            authorization = base + '/oauth/authorize?' + urlencode({
                'client_id': 'existing-form-client', 'redirect_uri': resource,
                'resource': resource if self.mode != 'wrong-resource' else base + '/form/different',
                'response_type': 'code', 'state': 'private-example-state',
                'code_challenge': 'example-pkce-challenge', 'code_challenge_method': 'S256'})
            return self.redirect(request, authorization)
        if parts.path == '/oauth/authorize':
            if self.mode == 'loop':
                return self.redirect(request, resource)
            if self.mode in {'consent', 'signin'}:
                return self.redirect(request, base + '/oauth/consent?request_id=private-example')
            if self.mode == 'cross-origin':
                return self.redirect(request, 'https://attacker.example/collect')
            return self.redirect(request, resource + '?code=private-example-code&state=private-example-state')
        if parts.path == '/oauth/consent':
            if self.mode == 'signin':
                return self.redirect(request, base + '/signin?redirect=private-example')
            return MockResponse('<html><h1>Approve access</h1><button>Approve</button></html>')
        if parts.path == '/form-waiting/example':
            if 'n8n-form-auth-wf-example=page-example' not in cookie:
                raise AssertionError('Signed page cookie was lost between requests')
            return MockResponse(COMPLETION)
        raise AssertionError('Unexpected request in OAuth test')


class OAuthAdapterTests(unittest.TestCase):
    def client(self, mode='success'):
        client = N8nClient(CONFIG, 'n8n-auth=example-session')
        client.opener = OAuthTransport(mode)
        return client

    def test_oauth_redirects_preserve_one_hop_cookie_and_return_form(self):
        client = self.client()
        page = client.request('/form/example')
        self.assertEqual(page['kind'], 'form')
        self.assertEqual(len(client.opener.calls), 4)
        self.assertEqual(client.last_form_url, CONFIG['n8n_url'] + '/form/example')
        self.assertTrue(all(r.get_method() == 'GET' for r in client.opener.calls))
        self.assertNotIn('private-example', json.dumps(public_error(client.auth_required())))

    def test_page_cookie_survives_into_waiting_page(self):
        client = self.client()
        client.request('/form/example')
        page = client.request('/form-waiting/example')
        self.assertEqual(page['kind'], 'completion')

    def test_interactive_consent_requires_user_and_is_never_posted(self):
        client = self.client('consent')
        with self.assertRaises(AuthenticationRequired) as caught:
            client.request('/form/example')
        public = public_error(caught.exception)
        self.assertTrue(public['auth_required'])
        self.assertEqual(public['auth_url'], CONFIG['n8n_url'] + '/form/example')
        self.assertNotIn('private-example', json.dumps(public))
        self.assertTrue(all(r.get_method() == 'GET' for r in client.opener.calls))

    def test_expired_session_returns_signin_handoff(self):
        client = self.client('signin')
        with self.assertRaises(AuthenticationRequired):
            client.request('/form/example')

    def test_authorization_for_a_different_form_is_rejected(self):
        client = self.client('wrong-resource')
        with self.assertRaises(SupportError):
            client.request('/form/example')
        self.assertEqual(len(client.opener.calls), 1)

    def test_oauth_never_sends_cookies_to_another_origin(self):
        client = self.client('cross-origin')
        with self.assertRaises(SupportError):
            client.request('/form/example')
        self.assertTrue(all(urlsplit(r.full_url).hostname == 'localhost' for r in client.opener.calls))

    def test_oauth_redirect_loop_has_a_fixed_limit(self):
        client = self.client('loop')
        with self.assertRaises(SupportError):
            client.request('/form/example')
        self.assertEqual(len(client.opener.calls), 10)

    def test_changed_browser_session_cannot_reuse_another_users_form_tokens(self):
        client = self.client()
        client.request('/form/example')
        with self.assertRaises(AuthenticationRequired):
            client.ensure_identity('n8n-auth=different-session')
        self.assertEqual(len(client.cookies), 0)

    def test_native_credential_shell_is_not_bypassed(self):
        page = parse_page('<html><h1>Connect accounts</h1><iframe src="/form/example?n8nShellInner=1"></iframe></html>')
        self.assertEqual(page['kind'], 'native_auth_shell')


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.factory = Factory()
        self.service = SupportService(CONFIG, self.factory)
        self.counter = 0

    def answer(self, sid, message=None, action='message', **extra):
        self.counter += 1
        return self.service.chat({'conversation_id': sid, 'message_id': 'message-' + str(self.counter),
                                  'message': message, 'action': action, **extra}, '')

    def ready(self):
        response = self.service.chat({'message': 'Edge zoom is too large.', 'action': 'message'}, '')
        sid = response['conversation_id']
        for value in ['alex@example.com', 'Only me', 'I can continue work in another tab; no deadlines.', 'Yes', 'Today']:
            response = self.answer(sid, value)
        self.assertEqual(response['phase'], 'ready')
        return sid, response

    def test_form_parser_preserves_exact_fields_choices_and_hidden_values(self):
        page = parse_page(form_html())
        self.assertEqual(len(page['fields']), 7)
        self.assertEqual(page['fields'][0]['name'], 'field-0')
        self.assertEqual(page['fields'][3]['options'], [{'label': 'Only me', 'value': 'Only me'}, {'label': 'My team', 'value': 'My team'}])
        self.assertEqual(page['hidden'], {'context': 'preserve me'})

    def test_no_submission_until_employee_explicitly_confirms(self):
        sid, ready = self.ready()
        self.assertEqual(len(ready['review']), 7)
        self.assertFalse(any(fields is not None for _, fields, _ in self.factory.calls))
        self.assertNotIn('example-not-a-real-secret', json.dumps(ready))

    def test_completion_returns_real_ticket_and_citation(self):
        sid, _ = self.ready()
        response = self.answer(sid, action='submit')
        self.assertEqual(response['phase'], 'complete')
        self.assertEqual(response['result']['ticket_key'], 'KAN-99')
        self.assertEqual(response['result']['kind'], 'guidance')
        self.assertEqual(response['result']['references'][0]['label'], 'KB-002')
        posts = [c for c in self.factory.calls if c[1] is not None]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][1]['context'], 'preserve me')
        self.assertEqual(posts[0][1]['field-2'], 'Edge zoom is too large.')

    def test_replayed_submit_does_not_create_a_second_post(self):
        sid, _ = self.ready()
        payload = {'conversation_id': sid, 'message_id': 'same-submit', 'action': 'submit'}
        first = self.service.chat(payload, '')
        second = self.service.chat(payload, '')
        self.assertEqual(first, second)
        self.assertEqual(sum(c[1] is not None for c in self.factory.calls), 1)
        with self.assertRaises(SupportError):
            self.answer(sid, action='submit')

    def test_invalid_email_keeps_the_current_question(self):
        start = self.service.chat({'message': 'VPN does not connect.'}, '')
        response = self.answer(start['conversation_id'], 'not an email')
        self.assertEqual(response['question']['type'], 'email')
        self.assertIn('complete email', response['message'])

    def test_edit_preserves_user_answer_and_requires_confirmation(self):
        sid, _ = self.ready()
        response = self.answer(sid, action='edit', field='field-1', value='Accidental Edge zoom')
        self.assertEqual(response['phase'], 'ready')
        self.assertEqual(response['review'][1]['value'], 'Accidental Edge zoom')
        self.assertFalse(any(c[1] is not None for c in self.factory.calls))

    def test_n8n_clarification_becomes_a_chat_question(self):
        clarification = parse_page('<form id="n8n-form"><label for="field-0">What error appears?</label><textarea name="field-0" id="field-0" class="form-required"></textarea></form>')
        self.factory.responses = [{'formWaitingUrl': 'http://localhost:5678/form-waiting/99?signature=example'}, parse_page(COMPLETION)]
        self.factory.pages = [clarification]
        sid, _ = self.ready()
        with patch('server.time.sleep'):
            response = self.answer(sid, action='submit')
        self.assertEqual(response['round'], 1)
        self.assertEqual(response['phase'], 'clarification')
        self.assertIn('What error appears?', response['message'])
        response = self.answer(sid, 'Error 502')
        self.assertEqual(response['phase'], 'ready')
        response = self.answer(sid, action='submit')
        self.assertEqual(response['result']['ticket_key'], 'KAN-99')
        self.assertIn('signature=example', self.factory.calls[-1][0])

    def test_timeout_does_not_retry_a_submission(self):
        self.factory.responses = [SupportError('Timed out', 503)]
        sid, _ = self.ready()
        response = self.answer(sid, action='submit')
        self.assertEqual(response['phase'], 'waiting')
        self.assertIn('may already exist', response['notice'])
        with self.assertRaises(SupportError):
            self.answer(sid, action='submit')
        response = self.answer(sid, action='resume')
        self.assertIn('unconfirmed', response['notice'])
        self.assertEqual(sum(c[1] is not None for c in self.factory.calls), 1)

    def test_success_without_confirmation_does_not_invent_a_ticket(self):
        self.factory.responses = [{'execution_status': 'success'}]
        sid, _ = self.ready()
        response = self.answer(sid, action='submit')
        self.assertIsNone(response['result']['ticket_key'])
        self.assertEqual(response['result']['kind'], 'unconfirmed')

    def test_result_does_not_execute_html_or_trust_other_citation_hosts(self):
        page = parse_page('<h1>Request registered</h1><div class="form-header"><p>KAN-88</p><script>alert(1)</script><a href="https://attacker.example/a">KB</a></div>')
        result = make_result(page, CONFIG['jira_url'])
        self.assertNotIn('alert', result['text'])
        self.assertEqual(result['references'], [])

    def test_unexpected_redirect_destination_is_rejected(self):
        client = N8nClient(CONFIG)
        for url in ['https://attacker.example/form/1', 'http://localhost:9999/form/1', 'http://localhost:5678/rest/credentials']:
            with self.assertRaises(SupportError):
                client.url(url)

    def test_only_n8n_session_cookie_is_forwarded(self):
        self.assertEqual(forwarded_cookie('unrelated=private; n8n-auth=example-session'), 'n8n-auth=example-session')

    def test_completion_without_ticket_is_unconfirmed(self):
        result = make_result({'title': 'Form submitted', 'text': 'Thank you.'}, CONFIG['jira_url'])
        self.assertIsNone(result['ticket_key'])
        self.assertEqual(result['kind'], 'unconfirmed')

    def test_choices_cannot_be_replaced_with_arbitrary_text(self):
        with self.assertRaises(SupportError):
            validate_answer({'options': [{'label': 'Only me', 'value': 'Only me'}]}, 'Everyone in the world')


if __name__ == '__main__':
    unittest.main(verbosity=2)
