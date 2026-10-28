import {consumeSSE} from './sse.js';
import {applyEvent, beginRun, createRunState, interruptRun} from './state.js';

const $ = id => document.getElementById(id);
const labels = {answered: ['已回答', 'badge-green'], needs_clarification: ['待澄清', 'badge-amber'], insufficient_evidence: ['资料不足', 'badge-amber'], incomplete: ['未完成', 'badge-red']};
const actionLabels = {search_documents: '检索制度资料', read_snippet: '读取原文条款', finish: '核对并整理结果'};
let state = createRunState();
let history = [];
let scenario = null;
let controller = null;
let timer = null;
let started = 0;
let assistant = null;
const traceRows = new Map();

// Dynamic data always enters the DOM through textContent, never innerHTML.
function el(tag, classes = '', text = '') { const node = document.createElement(tag); node.className = classes; node.textContent = text; return node; }
function badge(status) { const [name, color] = labels[status] || ['未完成', 'badge-red']; return el('span', `badge ${color}`, name); }
function showBanner(message) { $('banner').textContent = message; $('banner').classList.toggle('hidden', !message); }
function scrollChat() { $('conversation').scrollTop = $('conversation').scrollHeight; }
function setBusy(busy) {
  for (const id of ['send', 'mode', 'reset', 'question']) $(id).disabled = busy;
  document.querySelectorAll('[data-example]').forEach(button => { button.disabled = busy; });
  $('stop').classList.toggle('hidden', !busy);
  $('send').textContent = busy ? '处理中…' : '发送问题 ↗';
  $('download-result').disabled = !state.output;
  $('download-trace').disabled = !state.events.length;
}
function runStatus(text, color = 'badge-neutral') { $('run-status').className = `badge ${color}`; $('run-status').textContent = text; }
async function copyText(text, button) {
  try { await navigator.clipboard.writeText(text); button.textContent = '已复制'; setTimeout(() => { button.textContent = '复制'; }, 1600); }
  catch { showBanner('无法访问剪贴板，请选中文字复制。'); }
}
function copyButton(text) { const button = el('button', 'copy-btn', '复制'); button.type = 'button'; button.addEventListener('click', () => copyText(text, button)); return button; }

function message(role, text) {
  $('welcome').classList.add('hidden');
  const outer = el('article', role === 'user' ? 'ml-auto max-w-[90%] rounded-2xl rounded-tr-sm bg-blue-600 px-4 py-3 text-sm leading-7 text-white whitespace-pre-wrap break-words' : 'min-w-0');
  if (role === 'user') outer.textContent = text;
  else {
    const title = el('div', 'mb-3 flex items-center gap-2 text-xs font-medium text-slate-500');
    title.append(el('span', 'flex size-6 items-center justify-center rounded-lg bg-blue-50 text-blue-600', '据'), el('span', '', '知据助手'));
    outer.append(title);
  }
  $('messages').append(outer);
  scrollChat();
  return outer;
}

function renderOutput(output) {
  const wrap = el('div', 'min-w-0');
  const heading = el('div', 'mb-3 flex items-center justify-between gap-2');
  heading.append(badge(output.status), copyButton(output.answer));
  wrap.append(heading, el('p', 'answer-text', output.answer));
  if (output.conflicts.length) {
    const box = el('div', 'mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3');
    box.append(el('h3', 'text-sm font-semibold text-amber-900', '制度存在冲突'));
    output.conflicts.forEach(conflict => box.append(el('p', 'mt-2 text-xs leading-6 text-amber-900', `${conflict.document_ids.join(' / ')} · ${conflict.description}`)));
    wrap.append(box);
  }
  if (output.citations.length) wrap.append(el('h3', 'mb-1 mt-5 text-xs font-semibold text-slate-500', `原文依据 · ${output.citations.length} 处`));
  output.citations.forEach(citation => {
    const card = el('div', 'citation-card');
    const top = el('div', 'mb-2 flex flex-wrap items-center justify-between gap-1');
    const meta = el('span', 'text-[11px] text-slate-500', `${citation.document_id} · ${citation.title} · ${citation.version_date}`);
    top.append(meta, copyButton(citation.quote));
    card.append(top, el('blockquote', 'border-l-2 border-blue-300 pl-3 text-xs leading-6 text-slate-700 whitespace-pre-wrap break-words', citation.quote));
    const details = el('details', 'mt-2');
    details.append(el('summary', 'cursor-pointer text-[11px] text-blue-600', `查看完整片段 ${citation.snippet_id}`), el('p', 'mt-2 whitespace-pre-wrap break-words text-xs leading-6 text-slate-500', citation.snippet_text));
    card.append(details); wrap.append(card);
  });
  if (output.gaps.length) {
    const gaps = el('div', 'mt-4 rounded-lg bg-slate-50 px-3 py-3');
    gaps.append(el('h3', 'text-xs font-semibold text-slate-600', '资料缺口'));
    output.gaps.forEach(gap => gaps.append(el('p', 'mt-1 text-xs leading-6 text-slate-500', `• ${gap}`)));
    wrap.append(gaps);
  }
  if (output.follow_up_question) wrap.append(el('p', 'mt-4 rounded-lg border border-blue-100 bg-blue-50 px-3 py-3 text-sm leading-6 text-blue-800', output.follow_up_question));
  assistant.querySelector('[data-pending]')?.remove();
  assistant.append(wrap);
  const [name, color] = labels[output.status];
  runStatus(name, color);
  scrollChat();
}

function onEvent(event) {
  state = applyEvent(state, event);
  const p = event.payload;
  if (event.event === 'run_started') {
    $('run-meta').textContent = `运行 ${event.run_id.slice(0, 12)} · 资料 ${p.corpus_hash.slice(0, 12)}`;
  } else if (event.event === 'action') {
    $('trace-empty').classList.add('hidden');
    const row = el('li', 'flex min-w-0 gap-3');
    row.append(el('span', 'trace-number', String(event.step).padStart(2, '0')));
    const body = el('div', 'min-w-0 flex-1');
    body.append(el('h3', 'text-xs font-semibold text-slate-700', actionLabels[p.action]), el('p', 'mt-1 text-[11px] leading-5 text-slate-400', p.decision_summary));
    const details = el('details', 'mt-1.5');
    details.append(el('summary', 'cursor-pointer text-[10px] text-slate-400', '查看参数'), el('pre', 'mt-2 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-slate-50 p-2 text-[10px] text-slate-500', JSON.stringify(p.arguments, null, 2)));
    body.append(details); row.append(body); $('trace').append(row); traceRows.set(event.step, body);
  } else if (event.event === 'tool_result') {
    const row = traceRows.get(event.step) || $('trace');
    row.append(el('p', `mt-1.5 text-[11px] leading-5 ${p.ok ? 'text-emerald-600' : 'text-red-600'}`, `${p.ok ? '✓' : '工具失败 ·'} ${p.summary} · ${p.elapsed_ms} ms`));
  } else if (event.event === 'validation_error') {
    $('trace-empty').classList.add('hidden');
    $('trace').append(el('li', 'rounded-lg bg-amber-50 px-3 py-2 text-xs leading-6 text-amber-800', `校验反馈：${p.summary}`));
  } else if (event.event === 'final') {
    clearInterval(timer);
    $('elapsed').textContent = `${(p.elapsed_ms / 1000).toFixed(1)} s`;
    renderOutput(p.output);
  }
}

$('ask-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (state.phase === 'running') return;
  const question = $('question').value.trim();
  if (!question) { $('question').focus(); return; }
  showBanner('');
  state = beginRun();
  $('trace').replaceChildren(); traceRows.clear(); $('trace-empty').classList.remove('hidden'); $('run-meta').textContent = '';
  message('user', question);
  assistant = message('assistant');
  const pending = el('p', 'text-sm text-slate-400', '正在查找资料，请稍候…'); pending.dataset.pending = 'true'; assistant.append(pending);
  controller = new AbortController();
  setBusy(true); runStatus('执行中', 'badge-blue');
  started = performance.now(); timer = setInterval(() => { $('elapsed').textContent = `${((performance.now() - started) / 1000).toFixed(1)} s`; }, 100);
  try {
    const response = await fetch('/api/ask', {method: 'POST', headers: {'Content-Type': 'application/json', 'Accept': 'text/event-stream'}, body: JSON.stringify({question, history, mode: $('mode').value, scenario_id: scenario}), signal: controller.signal});
    await consumeSSE(response, onEvent);
    if (state.output && state.output.status !== 'incomplete') {
      history.push({role: 'user', content: question}, {role: 'assistant', content: state.output.answer + (state.output.follow_up_question ? '\n' + state.output.follow_up_question : '')});
      history = history.slice(-20);
    }
    $('question').value = '';
  } catch (error) {
    // A final output stays final even if cleanup fails afterwards.
    if (!state.output) {
      state = interruptRun(state);
      const text = error.name === 'AbortError' ? '已停止，本次任务未完成。' : error.message;
      assistant.querySelector('[data-pending]')?.remove();
      assistant.append(el('p', 'rounded-lg border border-red-100 bg-red-50 p-3 text-sm leading-6 text-red-700', text));
      runStatus('未完成', 'badge-red');
      showBanner(text);
    }
  } finally {
    clearInterval(timer); controller = null; setBusy(false); scrollChat();
  }
});
$('question').addEventListener('keydown', event => { if (event.ctrlKey && event.key === 'Enter') { event.preventDefault(); $('ask-form').requestSubmit(); } });
$('stop').addEventListener('click', () => controller?.abort());
$('mode').addEventListener('change', () => { $('mode-note').textContent = $('mode').value === 'mock' ? '离线演示 · 仅验证流程，不证明真实模型决策效果' : '真实模型 · 仅依据读取的资料回答，请核对引用'; });
$('reset').addEventListener('click', () => {
  history = []; scenario = null; state = createRunState(); assistant = null;
  $('messages').replaceChildren(); $('welcome').classList.remove('hidden'); $('question').value = ''; $('trace').replaceChildren(); traceRows.clear();
  $('trace-empty').classList.remove('hidden'); $('run-meta').textContent = ''; $('elapsed').textContent = '—'; $('scenario-label').textContent = '完整制度资料库';
  runStatus('等待提问'); showBanner(''); setBusy(false); $('question').focus();
});
function download(filename, body, type = 'application/json') { const url = URL.createObjectURL(new Blob([body], {type})); const a = el('a'); a.href = url; a.download = filename; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
$('download-result').addEventListener('click', () => { if (state.output) download(`${state.runId}-output.json`, JSON.stringify(state.output, null, 2)); });
$('download-trace').addEventListener('click', () => {
  const metadata = {client_export: true, incomplete: state.phase !== 'finished', run_id: state.runId};
  download(`${state.runId || 'interrupted'}-trace.jsonl`, [JSON.stringify(metadata), ...state.events.map(e => JSON.stringify(e))].join('\n') + '\n', 'application/x-ndjson');
});

async function init() {
  if (!matchMedia('(min-width: 1024px)').matches) $('trace-panel').open = false;
  try {
    const [healthResponse, examplesResponse] = await Promise.all([fetch('/api/health'), fetch('/api/examples')]);
    if (!healthResponse.ok || !examplesResponse.ok) throw new Error('服务连接失败，请刷新页面后重试。');
    const health = await healthResponse.json();
    $('connection').replaceChildren(el('span', 'size-1.5 rounded-full bg-emerald-500'), el('span', '', '服务已连接'));
    if (health.model_configured) { const live = $('mode').querySelector('[value="live"]'); live.disabled = false; live.textContent = '真实模型'; }
    const {examples} = await examplesResponse.json();
    examples.forEach((item, index) => {
      const button = el('button', 'example-card'); button.type = 'button'; button.dataset.example = item.id;
      button.append(el('span', 'mt-0.5 text-[10px] tabular-nums text-blue-400', String(index + 1).padStart(2, '0')));
      const text = el('span', 'min-w-0'); text.append(el('span', 'block text-xs font-medium text-slate-700', item.title), el('span', 'mt-1 block text-[11px] leading-5 text-slate-400', item.question)); button.append(text);
      button.addEventListener('click', () => {
        if (state.phase === 'running') return;
        history = item.history.map(m => ({...m})); scenario = item.id;
        $('question').value = item.question; $('scenario-label').textContent = `演示场景：${item.title}`;
        showBanner('');
        $('messages').replaceChildren(); $('welcome').classList.remove('hidden');
        history.forEach(m => { const node = message(m.role, m.content); if (m.role === 'assistant') node.append(el('p', 'answer-text', m.content)); });
        $('question').focus();
      });
      button.title = item.description;
      $('examples').append(button);
    });
  } catch (error) {
    $('connection').replaceChildren(el('span', 'size-1.5 rounded-full bg-red-400'), el('span', '', '连接失败'));
    showBanner(error.message);
  }
}
init();
