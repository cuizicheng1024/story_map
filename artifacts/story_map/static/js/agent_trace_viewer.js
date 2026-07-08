/* agent_trace_viewer.js — agent_v2 trace 可视化
 *
 * 设计原则:
 * 1) 单文件,只依赖 fetch + DOM — 跑在任意 static host(GitHub Pages / 火山云 / OpenDeploy)
 * 2) 自动从 query ?traces=... 加载 JSON,或从页面 dropzone / URL list 加载
 * 3) timeline 横向展示 agent steps,可点击展开 step detail
 * 4) token 统计 + debate round 信息单独展示
 */
(function (global) {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));
  const el = (tag, attrs) => {
    const node = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (k === 'class') node.className = v;
      else if (k === 'text') node.textContent = v;
      else if (k === 'html') node.innerHTML = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
    return node;
  };

  // ==========================================================================
  // 数据加载
  // ==========================================================================
  async function loadTraces(sources) {
    const out = [];
    for (const src of sources) {
      try {
        const r = await fetch(src, { cache: 'no-cache' });
        if (!r.ok) continue;
        out.push({ source: src, data: await r.json() });
      } catch (e) {
        console.warn('load trace failed', src, e);
      }
    }
    return out;
  }

  // ==========================================================================
  // 渲染 — 主入口
  // ==========================================================================
  function render(trace) {
    const root = $('#atv-root');
    root.innerHTML = '';
    if (!trace || !trace.events) {
      root.appendChild(el('div', { class: 'atv-empty', text: 'no events' }));
      return;
    }
    const stats = trace.stats || {};
    const tokens = stats.tokens || { input: 0, output: 0 };

    // Header summary
    const header = el('div', { class: 'atv-header' });
    header.innerHTML = `
      <div class="atv-title">Run ${trace.run_id || '?'}</div>
      <div class="atv-stats">
        <span class="badge">events: ${stats.events_total || trace.events.length}</span>
        <span class="badge">tokens in: ${tokens.input.toLocaleString()}</span>
        <span class="badge">tokens out: ${tokens.output.toLocaleString()}</span>
        <span class="badge">total: ${(tokens.input + tokens.output).toLocaleString()}</span>
        <span class="badge atv-kinds">${Object.entries(stats.kinds || {}).map(([k, v]) => `${k}:${v}`).join(' · ')}</span>
      </div>
    `;
    root.appendChild(header);

    // Build task list per agent
    const agentTasks = groupByAgent(trace.events);

    // Timeline
    root.appendChild(renderTimeline(trace.events));

    // Per-agent step list
    const sections = el('div', { class: 'atv-sections' });
    for (const agent of Object.keys(agentTasks)) {
      sections.appendChild(renderAgentSection(agent, agentTasks[agent]));
    }
    root.appendChild(sections);

    // Debate round summary
    const debate = trace.events.filter((e) => e.kind === 'debate_round');
    if (debate.length > 0) {
      root.appendChild(renderDebate(debate, trace.events));
    }
  }

  function groupByAgent(events) {
    const out = {};
    let cur = null;
    for (const e of events) {
      if (e.kind === 'run_start') {
        cur = e.agent;
        out[cur] = out[cur] || [];
        out[cur].push({ kind: 'header', goal: e.payload?.goal || '' });
      } else if (cur && out[cur]) {
        out[cur].push(e);
        if (e.kind === 'run_finish') cur = null;
      }
    }
    return out;
  }

  // ==========================================================================
  // Timeline
  // ==========================================================================
  function renderTimeline(events) {
    const wrap = el('div', { class: 'atv-timeline-wrap' });
    wrap.appendChild(el('div', { class: 'atv-section-title', text: 'Time-line' }));
    const tl = el('div', { class: 'atv-timeline' });
    const totalEvents = events.length;
    events.forEach((e, i) => {
      const xPct = (i / Math.max(1, totalEvents - 1)) * 100;
      const dot = el('div', {
        class: `atv-dot atv-dot-${e.kind}`,
        title: `${e.kind} · ${e.agent}\n${JSON.stringify(e.payload).slice(0, 200)}`,
      });
      dot.style.left = `${xPct}%`;
      dot.addEventListener('click', () => {
        showStepDetail(e);
      });
      tl.appendChild(dot);
    });
    wrap.appendChild(tl);
    return wrap;
  }

  function showStepDetail(e) {
    const panel = $('#atv-detail');
    if (!panel) return;
    panel.innerHTML = '';
    panel.appendChild(el('div', { class: 'atv-detail-title', text: `${e.kind}  ·  ${e.agent}` }));
    panel.appendChild(el('pre', { class: 'atv-detail-json', text: JSON.stringify(e.payload, null, 2) }));
    panel.scrollIntoView({ behavior: 'smooth' });
  }

  // ==========================================================================
  // Agent sections
  // ==========================================================================
  function renderAgentSection(agent, evts) {
    const section = el('div', { class: 'atv-agent-section' });
    section.appendChild(el('div', { class: 'atv-agent-title', text: `agent: ${agent}` }));
    const list = el('div', { class: 'atv-step-list' });
    for (const e of evts) {
      if (e.kind === 'header') {
        list.appendChild(el('div', { class: 'atv-goal', text: `goal: ${e.goal}` }));
        continue;
      }
      const card = el('div', { class: `atv-step atv-step-${e.kind}` });
      const head = el('div', { class: 'atv-step-head' });
      head.appendChild(el('span', { class: 'atv-step-kind', text: e.kind }));
      head.appendChild(el('span', { class: 'atv-step-agent', text: e.agent }));
      if (e.payload?.tool) {
        head.appendChild(el('span', { class: 'atv-step-tool', text: e.payload.tool }));
      }
      card.appendChild(head);
      const body = el('pre', { class: 'atv-step-body', text: JSON.stringify(e.payload, null, 2) });
      card.appendChild(body);
      list.appendChild(card);
    }
    section.appendChild(list);
    return section;
  }

  // ==========================================================================
  // Debate summary
  // ==========================================================================
  function renderDebate(rounds, allEvents) {
    const wrap = el('div', { class: 'atv-debate' });
    wrap.appendChild(el('div', { class: 'atv-section-title', text: 'Debate-Reflect 轮次' }));
    const list = el('div', { class: 'atv-debate-list' });
    const critiques = allEvents.filter((e) => e.kind === 'critique_done');
    for (const c of critiques) {
      const card = el('div', { class: 'atv-critique' });
      const head = el('div', { class: 'atv-critique-head' });
      head.appendChild(el('span', { text: `Round ${c.payload.round}` }));
      head.appendChild(el('span', { class: `atv-sev atv-sev-${c.payload.severity}`, text: c.payload.severity }));
      head.appendChild(el('span', { text: `issues: ${c.payload.issues_n}` }));
      card.appendChild(head);
      list.appendChild(card);
    }
    wrap.appendChild(list);
    return wrap;
  }

  // ==========================================================================
  // 入口
  // ==========================================================================
  async function init() {
    return initWithRoot('atv-root');
  }

  async function initWithRoot(rootId, sources) {
    const root = document.getElementById(rootId);
    if (!root) return;
    if (!sources) {
      sources = await _discoverSources();
    }
    if (!sources || sources.length === 0) {
      root.appendChild(el('div', { class: 'atv-empty', text: '无 trace 数据。传入 ?trace=<url> 或上传 json。' }));
      setupUpload(rootId);
      return;
    }
    const traces = await loadTraces(sources);
    if (traces.length === 0) {
      root.appendChild(el('div', { class: 'atv-empty', text: '加载失败' }));
      return;
    }
    render(traces[0].data);
    setupUpload(rootId);
  }

  async function _discoverSources() {
    const sources = [];
    const params = new URLSearchParams(location.search);
    const tracesParam = params.get('traces');
    const traceParam = params.get('trace');
    if (traceParam) sources.push(traceParam);
    if (tracesParam) sources.push(...tracesParam.split(','));
    if (sources.length === 0) {
      try {
        const r = await fetch('/static/traces/manifest.json', { cache: 'no-cache' });
        if (r.ok) {
          const m = await r.json();
          if (Array.isArray(m)) sources.push(...m);
        }
      } catch (e) { /* ignore */ }
    }
    return sources;
  }

  // ==========================================================================
  // 实时 SSE 渲染 (orange-office 调用)
  // ==========================================================================
  async function attachLive(rootId, opts) {
    const root = document.getElementById(rootId);
    if (!root) return;
    root.innerHTML = '';
    root.appendChild(el('div', { class: 'atv-live-status', text: '连接中...' }));
    const evtList = el('div', { class: 'atv-live-events' });
    root.appendChild(evtList);
    const statusEl = root.firstChild;

    const person = opts.person;
    if (!person) {
      statusEl.textContent = '缺少 person 参数';
      return;
    }

    // 启动后端 run (后台)
    fetch('/api/agent_v2/run?person=' + encodeURIComponent(person), { method: 'POST' })
      .then(r => r.json())
      .then(s => {
        statusEl.textContent = s.finished ? `已完成 ${s.duration_ms}ms · ${s.debate_rounds} 轮 debate`
          : s.error ? `失败: ${s.error}` : '排队中...';
      })
      .catch(e => { statusEl.textContent = '后端无响应: ' + e; });

    // 订阅 SSE
    const es = new EventSource('/api/agent_v2/run/stream?person=' + encodeURIComponent(person));
    es.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data);
        const item = el('div', { class: 'atv-live-item atv-live-item-' + ev.kind });
        item.appendChild(el('span', { class: 'atv-live-kind', text: ev.kind }));
        item.appendChild(el('span', { class: 'atv-live-agent', text: ev.agent }));
        const payloadStr = JSON.stringify(ev.payload || {}).slice(0, 160);
        item.appendChild(el('span', { class: 'atv-live-payload', text: payloadStr }));
        evtList.appendChild(item);
        evtList.scrollTop = evtList.scrollHeight;
        if (ev.kind === 'coord_done') {
          statusEl.textContent = '完成';
          es.close();
        }
      } catch (err) {
        // 跳过非 JSON 心跳
      }
    };
    es.addEventListener('done', () => { statusEl.textContent = '完成 (SSE close)'; es.close(); });
    es.onerror = () => { statusEl.textContent = 'SSE 断开'; };
  }

  async function refreshTraces(rootId) {
    const root = document.getElementById(rootId);
    if (!root) return;
    const sources = await _discoverSources();
    if (!sources.length) {
      root.appendChild(el('div', { class: 'atv-empty', text: '尚无 trace' }));
      return;
    }
    const traces = await loadTraces(sources);
    if (traces.length) render(traces[0].data);
  }

  function setupUpload() {
    const dz = $('#atv-dropzone');
    if (!dz) return;
    dz.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('hover'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('hover'));
    dz.addEventListener('drop', (e) => {
      e.preventDefault();
      dz.classList.remove('hover');
      const f = e.dataTransfer.files[0];
      if (!f) return;
      const reader = new FileReader();
      reader.onload = () => {
        try { render(JSON.parse(reader.result)); } catch (err) { console.error(err); }
      };
      reader.readAsText(f);
    });
  }

  global.AgentTraceViewer = { init, render, loadTraces };
})(window);