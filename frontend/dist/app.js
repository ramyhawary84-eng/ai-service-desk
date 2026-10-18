'use strict';

const $ = id => document.getElementById(id);
const storageKey = 'it-assist-conversations-v1';
let conversations = [];
try { conversations = JSON.parse(sessionStorage.getItem(storageKey) || '[]'); } catch {}
if (!Array.isArray(conversations)) conversations = [];
conversations = conversations.slice(0, 10);
let current = conversations[0] || freshConversation();
let busy = false;
let config = {};

function freshConversation() {
  return {id: crypto.randomUUID(), serverId: null, subject: 'New conversation', messages: [], phase: 'new', overview: {}, question: null, review: null, result: null, error: null};
}
function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', '#i-' + name); svg.append(use); return svg;
}
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function save() {
  if (current.messages.length) {
    conversations = [current, ...conversations.filter(item => item.id !== current.id)].slice(0, 10);
  }
  try { sessionStorage.setItem(storageKey, JSON.stringify(conversations)); } catch {}
}
function addMessage(role, text) {
  current.messages.push({role, text, at: new Date().toISOString()}); save();
}
function safeLink(value, kind = 'reference') {
  try {
    const url = new URL(value);
    if (kind === 'local' && url.protocol === 'http:' && url.hostname === 'localhost' && url.port === '5678') return url.href;
    const jiraOrigin = config.jira_url ? new URL(config.jira_url).origin : null;
    if (!url.username && !url.password && url.protocol === 'https:' &&
        (url.origin === jiraOrigin || url.hostname === 'support.microsoft.com')) return url.href;
  } catch {}
  return null;
}
function renderHistory() {
  $('historyCount').textContent = String(conversations.length);
  $('history').replaceChildren();
  if (!conversations.length) {
    const p = el('p', 'history-empty', 'Your requests will appear here during this session.');
    $('history').append(p); return;
  }
  for (const item of conversations) {
    const button = el('button', 'history-item' + (item.id === current.id ? ' selected' : ''));
    button.disabled = busy;
    button.append(icon('chat'));
    const copy = el('span', 'history-copy');
    copy.append(el('strong', '', item.subject), el('small', '', item.result?.ticket_key || (item.phase === 'complete' ? 'Conversation completed' : 'In progress')));
    button.append(copy);
    button.addEventListener('click', () => { if (!busy) { current = item; render(); } });
    $('history').append(button);
  }
}
function renderOverview() {
  const map = {contextIssue: ['description', 'Tell us what’s happening'], contextScope: ['affected_scope', 'Not provided yet'], contextImpact: ['business_effect', 'Not provided yet'], contextDeadline: ['needed_by', 'Not provided yet']};
  for (const [id, [key, fallback]] of Object.entries(map)) {
    const value = current.overview?.[key];
    $(id).textContent = value || fallback;
    $(id).classList.toggle('muted', !value);
  }
  const completed = current.phase === 'complete';
  $('requestStatus').textContent = current.result?.ticket_key || (completed ? 'Check with IT' : current.phase === 'processing' ? 'Submitted' : 'Not submitted');
  $('requestStatus').classList.toggle('submitted', !!current.result?.ticket_key);
  const step = completed ? 2 : ['processing', 'clarification'].includes(current.phase) ? 1 : 0;
  for (const item of document.querySelectorAll('[data-step]')) {
    const number = Number(item.dataset.step);
    item.classList.toggle('active', number === step);
    item.classList.toggle('done', number < step || (completed && !!current.result?.ticket_key));
    item.querySelector('.step-number').textContent = number < step ? '✓' : String(number + 1);
  }
}
function messageNode(message) {
  const row = el('article', 'message ' + message.role);
  let avatar;
  if (message.role === 'assistant') {
    avatar = el('img', 'message-avatar'); avatar.src = '/mark.svg'; avatar.alt = '';
  } else avatar = el('span', 'message-avatar', 'YOU');
  const main = el('div', 'message-main');
  const meta = el('div', 'message-meta');
  meta.append(el('strong', '', message.role === 'assistant' ? 'IT Assist' : 'You'));
  if (message.role === 'assistant') meta.append(el('span', 'assistant-label', 'SUPPORT ASSISTANT'));
  const time = el('time', '', new Date(message.at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}));
  time.dateTime = message.at; meta.append(time);
  main.append(meta, el('p', 'message-text', message.text));
  row.append(avatar, main); return row;
}
function reviewCard() {
  const details = el('details', 'review-card');
  details.append(el('summary', '', 'Review your request · ' + current.review.length + ' details'));
  const fields = el('div', 'review-fields');
  for (const field of current.review) {
    const row = el('div', 'review-row');
    const copy = el('div'); copy.append(el('small', '', field.label), el('p', '', field.value || 'Not provided'));
    const edit = el('button', 'edit-button', 'Edit'); edit.type = 'button'; edit.disabled = busy;
    edit.addEventListener('click', () => showEdit(row, field));
    row.append(copy, edit); fields.append(row);
  }
  details.append(fields); return details;
}
function showEdit(row, field) {
  row.replaceChildren();
  const form = el('form', 'edit-form'); form.style.width = '100%';
  const label = el('label', '', field.label);
  const input = field.options?.length ? el('select', 'edit-input') : el('textarea', 'edit-input');
  input.id = 'edit-' + field.name; label.htmlFor = input.id;
  if (field.options?.length) for (const option of field.options) {
    const o = el('option', '', option.label); o.value = option.value; input.append(o);
  }
  input.value = field.value; input.maxLength = 8000;
  const button = el('button', 'primary-button', 'Save change'); button.type = 'submit';
  form.append(label, input, button); row.append(form); input.focus();
  form.addEventListener('submit', event => { event.preventDefault(); send({action: 'edit', field: field.name, value: input.value}, null); });
}
function outcomeCard() {
  const result = current.result;
  const card = el('div', 'ticket-card');
  const top = el('div', 'ticket-card-top');
  top.append(icon(result.ticket_key ? 'check' : 'clock'), el('strong', '', result.ticket_key || 'Confirmation unavailable'), el('span', '', result.kind === 'guidance' ? 'GUIDANCE PROVIDED' : result.kind === 'duplicate' ? 'EXISTING REQUEST' : result.ticket_key ? 'AWAITING IT REVIEW' : 'CHECK WITH IT'));
  const body = el('div', 'ticket-body');
  body.append(el('p', '', result.ticket_key ? 'Keep this reference if you need further help. Your issue has not been confirmed resolved.' : 'The workflow did not return a ticket confirmation. Please check with IT before submitting again.'));
  const href = safeLink(result.ticket_url);
  if (href) {
    const link = el('a', 'ticket-link', 'Open request in Jira'); link.href = href; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.append(icon('external')); body.append(link);
  }
  if (result.references?.length) {
    const list = el('div', 'reference-list');
    for (const ref of result.references) {
      const href = safeLink(ref.url); if (!href) continue;
      const link = el('a', 'reference-link', ref.label || 'Knowledge reference');
      link.href = href; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.prepend(icon('book')); list.append(link);
    }
    body.append(list);
  }
  card.append(top, body); return card;
}
function render() {
  const started = current.messages.length > 0;
  $('welcome').classList.toggle('hidden', started);
  $('pageTitle').textContent = started ? (current.result?.ticket_key || 'Your conversation') : 'New conversation';
  $('messages').replaceChildren(...current.messages.map(messageNode));
  if (current.review?.length) {
    const target = $('messages').lastElementChild?.querySelector('.message-main');
    if (target) target.append(reviewCard());
  }
  if (current.result) {
    const target = $('messages').lastElementChild?.querySelector('.message-main');
    if (target) target.append(outcomeCard());
  }
  $('actions').replaceChildren();
  if (current.error) {
    $('actions').append(el('div', 'error-box', current.error));
    const authUrl = safeLink(current.authUrl, 'local');
    if (authUrl) {
      const signIn = el('a', 'secondary-button', 'Open employee sign-in ↗');
      signIn.href = authUrl; signIn.target = '_blank'; signIn.rel = 'noopener noreferrer';
      $('actions').append(signIn);
    }
    const help = el('button', 'secondary-button', 'Check workspace connection');
    help.addEventListener('click', () => $('connectionDialog').showModal()); $('actions').append(help);
    if (current.phase === 'waiting') {
      const resume = el('button', 'primary-button', 'Check for a response');
      resume.addEventListener('click', () => send({action: 'resume'}, null)); $('actions').append(resume);
    }
  }
  if (!busy && current.phase === 'ready') {
    const button = el('button', 'primary-button', current.serverRound > 0 ? 'Send follow-up details' : 'Submit request');
    button.append(icon('arrow'));
    button.addEventListener('click', () => send({action: 'submit'}, current.serverRound > 0 ? 'Send follow-up details' : 'Submit request'));
    $('actions').append(button);
  } else if (!busy && current.question?.options?.length && current.phase !== 'complete') {
    const choices = el('div', 'quick-replies');
    for (const option of current.question.options) {
      const button = el('button', 'quick-reply', option.label);
      button.addEventListener('click', () => send({action: 'message', message: option.value}, option.label)); choices.append(button);
    }
    $('actions').append(choices);
  }
  if (current.phase === 'complete') {
    const button = el('button', 'secondary-button', 'Start another conversation');
    button.addEventListener('click', startNew); $('actions').append(button);
  }
  $('typing').classList.toggle('hidden', !busy);
  $('typingLabel').textContent = current.phase === 'processing' ? 'Assessing your request and finding the next step…' : 'Connecting to IT support…';
  const inputDisabled = busy || ['ready', 'complete', 'waiting', 'processing'].includes(current.phase);
  $('messageInput').disabled = inputDisabled; $('sendButton').disabled = inputDisabled;
  $('messageInput').placeholder = busy ? 'Your request is being processed…' : current.phase === 'ready' ? 'Review your answers above, then submit your request.' : current.phase === 'complete' ? 'Start a new conversation for another request.' : current.question?.type === 'email' ? 'Enter your work email…' : current.question?.options?.length ? 'Choose an option above…' : started ? 'Type your answer…' : 'Describe your IT issue in your own words…';
  $('newRequest').disabled = busy; $('mobileNew').disabled = busy;
  renderHistory(); renderOverview();
  requestAnimationFrame(() => { $('conversationScroll').scrollTop = $('conversationScroll').scrollHeight; });
}
async function send(payload, visibleText) {
  if (busy) return;
  if (visibleText) {
    addMessage('user', visibleText);
    if (current.subject === 'New conversation') current.subject = visibleText.replace(/\s+/g, ' ').slice(0, 65);
  }
  const previousPhase = current.phase;
  if (payload.action === 'submit') current.phase = 'processing';
  current.error = null; current.review = null;
  busy = true; render();
  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({...payload, conversation_id: current.serverId, message_id: crypto.randomUUID()}),
      signal: AbortSignal.timeout(150000)
    });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error || 'The support service could not complete this step.');
      error.authUrl = data.auth_url || null;
      throw error;
    }
    current.serverId = data.conversation_id;
    current.phase = data.phase;
    current.serverRound = data.round || 0;
    current.overview = data.overview || current.overview;
    current.question = data.question || null;
    current.review = data.review || null;
    current.result = data.result || null;
    current.error = data.notice || null;
    current.authUrl = data.auth_url || null;
    if (data.message) addMessage('assistant', data.message);
    if (data.connected) setConnection(true, 'Connected to n8n');
  } catch (error) {
    current.phase = payload.action === 'submit' ? 'waiting' : previousPhase;
    current.error = error.name === 'TimeoutError' ? 'The response is taking longer than expected. The request may still be running. Check Jira before starting another submission.' : error.message;
    current.authUrl = error.authUrl || null;
    if (payload.action === 'submit') current.error += ' Submission status is unconfirmed; do not submit the same request again blindly.';
    setConnection(false, 'Connection needs attention');
    $('announcer').textContent = current.error;
  } finally {
    busy = false; save(); render();
    if (!$('messageInput').disabled) $('messageInput').focus();
  }
}
function setConnection(ok, text) {
  const badge = $('connectionBadge'); badge.classList.toggle('connected', ok); badge.classList.toggle('error', !ok);
  badge.replaceChildren(el('span'), document.createTextNode(text));
}
function startNew() {
  if (busy) return;
  if (current.messages.length && current.phase !== 'complete') $('newDialog').showModal();
  else resetConversation();
}
function resetConversation() { save(); current = freshConversation(); $('messageInput').value = ''; render(); $('messageInput').focus(); }
$('composer').addEventListener('submit', event => {
  event.preventDefault(); const message = $('messageInput').value.trim();
  if (!message || busy) return;
  $('messageInput').value = ''; $('messageInput').style.height = 'auto';
  send({action: 'message', message}, message);
});
$('messageInput').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('composer').requestSubmit(); }
});
$('messageInput').addEventListener('input', () => { $('messageInput').style.height = 'auto'; $('messageInput').style.height = Math.min($('messageInput').scrollHeight, 150) + 'px'; });
for (const button of document.querySelectorAll('[data-prompt]')) button.addEventListener('click', () => {
  $('messageInput').value = button.dataset.prompt; $('messageInput').focus();
  $('messageInput').setSelectionRange($('messageInput').value.length, $('messageInput').value.length);
});
$('newRequest').addEventListener('click', startNew); $('mobileNew').addEventListener('click', startNew);
$('confirmNew').addEventListener('click', () => { $('newDialog').close(); resetConversation(); });
$('helpButton').addEventListener('click', () => $('helpDialog').showModal());
$('connectionButton').addEventListener('click', () => $('connectionDialog').showModal());
for (const button of document.querySelectorAll('.close-dialog')) button.addEventListener('click', () => button.closest('dialog').close());
for (const dialog of document.querySelectorAll('dialog')) dialog.addEventListener('click', event => { if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close(); } });
$('checkConnection').addEventListener('click', async () => {
  $('checkConnection').disabled = true; $('connectionResult').textContent = 'Checking the employee form…';
  try {
    const response = await fetch('/api/check'); const data = await response.json();
    const signInUrl = safeLink(data.auth_url, 'local');
    $('employeeSignIn').classList.toggle('hidden', !signInUrl);
    if (signInUrl) $('employeeSignIn').href = signInUrl;
    if (!response.ok) throw new Error(data.error);
    $('connectionResult').textContent = 'Connected. The employee form is available. No request has been submitted.';
    $('connectionResult').classList.remove('error-text'); setConnection(true, 'Connected to n8n');
  } catch (error) {
    $('connectionResult').textContent = error.message || 'Could not connect to n8n.';
    $('connectionResult').classList.add('error-text'); setConnection(false, 'Connection needs attention');
  } finally { $('checkConnection').disabled = false; }
});
fetch('/api/health').then(response => response.json()).then(data => {
  config = data; $('configuredForm').textContent = data.form_url;
  const link = safeLink(data.workflow_url, 'local'); if (link) $('workflowLink').href = link;
  render();
}).catch(() => { $('configuredForm').textContent = 'The local support server is unavailable.'; });
render();
