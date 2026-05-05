// frontend/app.js
/**
 * BRD Specialist — Frontend Application
 *
 * Vanilla JS client for the BRD generation workflow.
 */

"use strict";

/* -- API Client ----------------------------------------------------------- */

const MAX_TIMINGS = 20;

class ApiClient {
  constructor(baseUrl = "") {
    this.baseUrl = baseUrl;
    this._timings = [];
    this._serverTimings = [];
  }

  async _request(path, options = {}) {
    const start = performance.now();
    let res;
    try {
      res = await fetch(`${this.baseUrl}${path}`, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
    } catch (err) {
      // Network errors (offline, DNS failure, etc.) throw TypeError.
      if (err instanceof TypeError) {
        throw new Error("Network error — check your connection");
      }
      throw err;
    }

    const durationMs = performance.now() - start;
    this._recordTiming(path, durationMs);
    const serverMs = parseFloat(res.headers.get("X-Response-Time-Ms") || "");
    if (!Number.isNaN(serverMs)) this._recordServerTiming(serverMs);

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed: ${res.status}`);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  _recordTiming(path, ms) {
    this._timings.push({ path, ms, at: Date.now() });
    if (this._timings.length > MAX_TIMINGS) this._timings.shift();
    updateResponseTimeUI();
  }

  _recordServerTiming(ms) {
    this._serverTimings.push(ms);
    if (this._serverTimings.length > MAX_TIMINGS) this._serverTimings.shift();
  }

  getAverageMs() {
    if (!this._timings.length) return 0;
    return this._timings.reduce((sum, t) => sum + t.ms, 0) / this._timings.length;
  }

  getAverageServerMs() {
    if (!this._serverTimings.length) return 0;
    return this._serverTimings.reduce((a, b) => a + b, 0) / this._serverTimings.length;
  }

  createConversation()      { return this._request("/conversations", { method: "POST" }); }
  getConversations()        { return this._request("/conversations"); }
  getConversation(id)       { return this._request(`/conversations/${encodeURIComponent(id)}`); }
  deleteConversation(id)    { return this._request(`/conversations/${encodeURIComponent(id)}`, { method: "DELETE" }); }
  sendMessage(id, content)  { return this._request(`/conversations/${encodeURIComponent(id)}/messages`, { method: "POST", body: JSON.stringify({ content }) }); }
  approve(id)               { return this._request(`/conversations/${encodeURIComponent(id)}/approve`, { method: "POST" }); }
  reject(id)                { return this._request(`/conversations/${encodeURIComponent(id)}/reject`, { method: "POST" }); }
  confirmEvidence(id)       { return this._request(`/conversations/${encodeURIComponent(id)}/confirm-evidence`, { method: "POST" }); }
  rejectEvidence(id)        { return this._request(`/conversations/${encodeURIComponent(id)}/reject-evidence`, { method: "POST" }); }

  /**
   * Streaming variant of sendMessage that consumes SSE frames from the orchestrator.
   * Calls onToken(text) for each "token" event, onDone(conversation) when complete,
   * and onError(message) if the stream fails. Returns a promise that resolves when
   * the stream ends (either via "done" or "error").
   */
  async sendMessageStream(id, content, { onToken, onDone, onError } = {}) {
    const start = performance.now();
    let firstTokenAt = null;
    let res;
    try {
      res = await fetch(
        `${this.baseUrl}/conversations/${encodeURIComponent(id)}/messages/stream`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content }),
        },
      );
    } catch (err) {
      const msg = err instanceof TypeError ? "Network error — check your connection" : err.message;
      if (onError) onError(msg);
      return;
    }

    if (!res.ok || !res.body) {
      const body = await res.json().catch(() => ({}));
      if (onError) onError(body.detail || `Request failed: ${res.status}`);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    // Parse SSE frames: each frame is "event: X\ndata: {...}\n\n".
    const consumeFrames = () => {
      let idx;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        let event = "message";
        const dataLines = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        let payload = null;
        if (dataLines.length) {
          try { payload = JSON.parse(dataLines.join("\n")); }
          catch { payload = { raw: dataLines.join("\n") }; }
        }
        if (event === "token" && payload && typeof payload.text === "string") {
          if (firstTokenAt === null) firstTokenAt = performance.now() - start;
          if (onToken) onToken(payload.text);
        } else if (event === "done") {
          const total = performance.now() - start;
          this._recordTiming("/conversations/:id/messages/stream", total);
          if (onDone) onDone(payload ? payload.conversation : null, { firstTokenMs: firstTokenAt, totalMs: total });
        } else if (event === "error") {
          if (onError) onError(payload && payload.message ? payload.message : "Stream failed");
        }
      }
    };

    while (true) {
      let chunk;
      try {
        chunk = await reader.read();
      } catch (err) {
        if (onError) onError(err.message || "Stream read failed");
        return;
      }
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      consumeFrames();
    }
    // Flush any remaining complete frame without trailing \n\n.
    if (buffer.trim()) {
      buffer += "\n\n";
      consumeFrames();
    }
  }
}

const api = new ApiClient();
const supportsStreaming = typeof ReadableStream !== "undefined" && typeof TextDecoder !== "undefined";

/* -- State ---------------------------------------------------------------- */

let conversations = [];
let selectedId = null;
let currentConv = null;
let sidebarPollTimer = null;
let sidebarLoading = true;

/* -- DOM refs ------------------------------------------------------------- */

const $ = (sel) => document.querySelector(sel);
const sidebar       = $("#sidebar");
const backdrop      = $("#backdrop");
const menuBtn       = $("#menu-btn");
const convList      = $("#conversation-list");
const contentArea   = $("#content-area");
const messageForm   = $("#message-form");
const messageInput  = $("#message-input");
const sendBtn       = $("#send-btn");
const toastBox      = $("#toast-container");
const logPanel      = $("#log-panel");
const logToggle     = $("#log-toggle");
const logBody       = $("#log-body");
const newChatBtn    = $("#new-chat-btn");
const responseTimeEl = $("#response-time");

const SEND_BTN_HTML = sendBtn.innerHTML;
const TEXTAREA_MAX_ROWS = 6;

/* -- Helpers -------------------------------------------------------------- */

function fmtTime(iso) {
  try { return new Date(iso).toLocaleTimeString(); }
  catch { return iso; }
}

const HTML_ESCAPE = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (m) => HTML_ESCAPE[m]);
}

function showToast(msg) {
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = `<span>${escapeHtml(msg)}</span><button aria-label="Close">&times;</button>`;
  let timeoutId = null;
  const remove = () => {
    if (timeoutId) { clearTimeout(timeoutId); timeoutId = null; }
    if (el.isConnected) el.remove();
  };
  el.querySelector("button").onclick = remove;
  toastBox.appendChild(el);
  timeoutId = setTimeout(remove, 6000);
}

function updateResponseTimeUI() {
  if (!responseTimeEl) return;
  const avg = api.getAverageMs();
  if (!avg) { responseTimeEl.textContent = ""; return; }
  const secs = avg / 1000;
  responseTimeEl.textContent = secs >= 1
    ? `Avg response: ${secs.toFixed(1)}s`
    : `Avg response: ${Math.round(avg)}ms`;
}

/* -- Render: sidebar conversation list ------------------------------------ */

function renderSidebar() {
  if (sidebarLoading) {
    convList.innerHTML = `
      <div class="sidebar-loading">
        <div class="sidebar-skeleton"></div>
        <div class="sidebar-skeleton"></div>
        <div class="sidebar-skeleton"></div>
      </div>`;
    return;
  }

  if (!conversations.length) {
    convList.innerHTML = `
      <div class="empty-state">
        <p class="empty-title">No documents yet</p>
        <p class="empty-sub">Start a new BRD to begin</p>
      </div>`;
    return;
  }

  convList.innerHTML = conversations.map((c) => `
    <div class="conv-item ${c.id === selectedId ? "active" : ""}" data-id="${escapeHtml(c.id)}" role="button" tabindex="0">
      <div class="conv-item-body">
        <div class="conv-item-title">${escapeHtml(c.title)}</div>
        <div class="conv-item-time">${fmtTime(c.updated_at)}</div>
      </div>
      ${c.status !== "active" ? `<span class="conv-item-warning" title="${escapeHtml(c.status)}">&#9888;</span>` : ""}
      <button class="delete-btn" data-delete="${escapeHtml(c.id)}" title="Delete conversation" aria-label="Delete conversation">&times;</button>
    </div>
  `).join("");

  convList.querySelectorAll(".conv-item").forEach((el) => {
    const activate = () => {
      selectConversation(el.dataset.id);
      closeSidebar();
    };
    el.addEventListener("click", (e) => {
      if (e.target.closest(".delete-btn")) return;
      activate();
    });
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        activate();
      }
    });
  });

  convList.querySelectorAll(".delete-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = btn.dataset.delete;
      try {
        await api.deleteConversation(id);
        if (selectedId === id) {
          selectedId = null;
          currentConv = null;
          renderContent();
          updateInput();
        }
        await fetchConversations();
      } catch (err) {
        showToast(err.message);
      }
    });
  });
}

/* -- Markdown + BRD formatting -------------------------------------------- */

const BRD_HEADINGS = [
  "Problem Statement",
  "Scope and Exclusions",
  "Functional Requirements",
  "Assumptions and Constraints",
  "Risks and Open Questions",
];

// Configure marked once. GFM + breaks gives us tables, fenced code, and
// newline-as-<br> which matches how the LLM tends to format output.
if (window.marked && typeof window.marked.setOptions === "function") {
  window.marked.setOptions({ gfm: true, breaks: true, mangle: false, headerIds: false });
}

function renderMarkdown(text) {
  const parser = window.marked;
  const sanitizer = window.DOMPurify;
  // Fallback: if either library failed to load, escape and preserve newlines.
  if (!parser || !sanitizer) {
    return `<pre class="md-fallback">${escapeHtml(text)}</pre>`;
  }
  const raw = parser.parse(String(text || ""));
  return sanitizer.sanitize(raw, { USE_PROFILES: { html: true } });
}

function formatEvidenceSummary(text) {
  return renderMarkdown(text);
}

function isBrdDocument(text) {
  const lower = String(text || "").toLowerCase();
  let matches = 0;
  for (const h of BRD_HEADINGS) {
    if (lower.includes(h.toLowerCase())) matches++;
  }
  return matches >= 3;
}

function formatBrdDocument(text) {
  return renderMarkdown(text);
}

/* -- Render: main content area -------------------------------------------- */

function renderContent() {
  if (!currentConv) {
    contentArea.innerHTML = `
      <div class="welcome">
        <svg class="welcome-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>
        </svg>
        <h2>BRD Specialist</h2>
        <p>Describe your requirements and I'll generate a Business Requirements Document</p>
        <div class="welcome-hints">
          <button type="button" class="welcome-hint" data-hint="Fetch records and draft a BRD">Fetch records and draft a BRD</button>
          <button type="button" class="welcome-hint" data-hint="Analyse data and create requirements">Analyse data and create requirements</button>
          <button type="button" class="welcome-hint" data-hint="Review evidence and generate docs">Review evidence and generate docs</button>
        </div>
      </div>`;
    contentArea.querySelectorAll(".welcome-hint").forEach((btn) => {
      btn.addEventListener("click", () => useWelcomeHint(btn.dataset.hint));
    });
    return;
  }

  const c = currentConv;
  let html = "";

  if (c.messages && c.messages.length) {
    html += `<div class="chat-thread">`;
    for (const msg of c.messages) {
      const isUser = msg.role === "user";
      const isBrd = !isUser && isBrdDocument(msg.content);
      if (isBrd) {
        html += `
          <div class="chat-msg chat-msg-agent" data-msg-index="${c.messages.indexOf(msg)}">
            <div class="chat-msg-label">Agent <span class="chat-msg-time">${fmtTime(msg.timestamp)}</span></div>
            <div class="brd-document">
              <div class="brd-document-header">
                <span class="brd-document-badge">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                  BRD
                </span>
                <span class="brd-document-label">Business Requirements Document</span>
                <button class="copy-btn copy-btn-inline" data-copy-msg="${c.messages.indexOf(msg)}" title="Copy BRD" aria-label="Copy BRD">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                  <span>Copy</span>
                </button>
              </div>
              <div class="brd-document-body md-body">${formatBrdDocument(msg.content)}</div>
            </div>
          </div>`;
      } else {
        const body = isUser
          ? escapeHtml(msg.content)
          : `<div class="md-body">${renderMarkdown(msg.content)}</div>`;
        html += `
          <div class="chat-msg ${isUser ? "chat-msg-user" : "chat-msg-agent"}" data-msg-index="${c.messages.indexOf(msg)}">
            <div class="chat-msg-label">${isUser ? "You" : "Agent"} <span class="chat-msg-time">${fmtTime(msg.timestamp)}</span></div>
            <div class="chat-msg-content">${body}</div>
            ${isUser ? "" : `<button class="copy-btn" data-copy-msg="${c.messages.indexOf(msg)}" title="Copy message" aria-label="Copy message">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              <span>Copy</span>
            </button>`}
          </div>`;
      }
    }
    html += `</div>`;
  }

  if (c.status === "awaiting_approval" && c.review_verdict) {
    const isReject = c.review_recommended_reject;
    const heading = isReject
      ? "Safety Reviewer Recommends Rejection"
      : "Human Approval Required";
    const desc = isReject
      ? "The safety reviewer recommends rejecting this query. You may override this decision."
      : "The safety reviewer approved this destructive query, but it requires your confirmation before execution.";
    html += `
      <div class="approval-box${isReject ? " approval-box-reject" : ""}">
        <h3>${heading}</h3>
        <p>${desc}</p>
        <div class="approval-verdict">${escapeHtml(c.review_verdict)}</div>
        <div class="approval-actions">
          <button class="btn-approve" data-action="approve">&#10003; Approve &amp; Execute</button>
          <button class="btn-reject" data-action="reject">&#10007; Reject</button>
        </div>
      </div>`;
  }

  if (c.status === "awaiting_brd_confirmation" && c.evidence_summary) {
    html += `
      <div class="brd-card">
        <div class="brd-card-header">
          <div class="brd-card-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
          </div>
          <div>
            <div class="brd-card-title">Evidence Summary Ready</div>
            <div class="brd-card-subtitle">Review the findings below, then confirm to generate the BRD</div>
          </div>
        </div>
        <div class="brd-progress">
          <div class="brd-step done"><span class="brd-step-num">&#10003;</span> Fetch Data</div>
          <span class="brd-step-connector"></span>
          <div class="brd-step active"><span class="brd-step-num">2</span> Review Evidence</div>
          <span class="brd-step-connector"></span>
          <div class="brd-step"><span class="brd-step-num">3</span> Draft BRD</div>
        </div>
        <div class="brd-evidence">${formatEvidenceSummary(c.evidence_summary)}</div>
        <div class="brd-card-actions">
          <button class="brd-btn-confirm" data-action="confirm-evidence">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="20 6 9 17 4 12"/></svg>
            Confirm &amp; Draft BRD
          </button>
          <button class="brd-btn-cancel" data-action="reject-evidence">Cancel</button>
        </div>
      </div>`;
  }

  if (c.events && c.events.length) {
    html += `
      <div class="activity-log">
        <div class="activity-header" id="activity-toggle">
          <span class="activity-title">Agent Activity (${c.events.length})</span>
          <button class="activity-toggle">Show</button>
        </div>
        <div class="activity-body collapsed" id="activity-body">
          <ul class="activity-list">
            ${c.events.map((e) => `
              <li>
                <div class="activity-meta">
                  <span>${fmtTime(e.timestamp)}</span>
                  <span class="activity-agent agent-${e.agent}">${escapeHtml(e.agent)}</span>
                  <span>${escapeHtml(e.action)}</span>
                </div>
                ${e.detail ? `<div class="activity-detail">${escapeHtml(e.detail)}</div>` : ""}
              </li>
            `).join("")}
          </ul>
        </div>
      </div>`;
  }

  contentArea.innerHTML = html;

  contentArea.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const action = btn.dataset.action;
      try {
        if (action === "approve") {
          currentConv = await api.approve(c.id);
        } else if (action === "reject") {
          currentConv = await api.reject(c.id);
        } else if (action === "confirm-evidence") {
          currentConv = await api.confirmEvidence(c.id);
        } else if (action === "reject-evidence") {
          currentConv = await api.rejectEvidence(c.id);
        }
        renderContent();
        updateInput();
        await fetchConversations();
      } catch (err) {
        showToast(err.message);
      }
    });
  });

  const actToggle = $("#activity-toggle");
  if (actToggle) {
    actToggle.addEventListener("click", () => {
      const body = $("#activity-body");
      const btn = actToggle.querySelector(".activity-toggle");
      body.classList.toggle("collapsed");
      btn.textContent = body.classList.contains("collapsed") ? "Show" : "Hide";
    });
  }

  contentArea.querySelectorAll("[data-copy-msg]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const idx = Number(btn.dataset.copyMsg);
      const msg = c.messages?.[idx];
      if (!msg) return;
      try {
        await copyToClipboard(msg.content);
        showToast("Copied to clipboard");
      } catch {
        showToast("Copy failed");
      }
    });
  });

  maybeScrollToBottom();
}

async function copyToClipboard(text) {
  // Prefer the async Clipboard API. Fall back to a hidden textarea for
  // older browsers / insecure contexts (file://, http without TLS).
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "absolute";
  ta.style.left = "-9999px";
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand("copy");
  } finally {
    ta.remove();
  }
}

/* -- Typing / streaming bubble ------------------------------------------- */

// Scroll anchoring: only auto-scroll while the user is reading the tail. If
// they scroll up to read an earlier part of the conversation, we leave them
// alone until they scroll back near the bottom.
const SCROLL_STICK_PX = 80;
let _userNearBottom = true;

function isNearBottom() {
  const main = $("#main-scroll");
  if (!main) return true;
  return (main.scrollHeight - main.scrollTop - main.clientHeight) < SCROLL_STICK_PX;
}

function maybeScrollToBottom() {
  if (!_userNearBottom) return;
  scrollMainToBottom();
}

function scrollMainToBottom() {
  const main = $("#main-scroll");
  if (main) main.scrollTop = main.scrollHeight;
  _userNearBottom = true;
}

function initScrollTracking() {
  const main = $("#main-scroll");
  if (!main) return;
  main.addEventListener("scroll", () => {
    _userNearBottom = isNearBottom();
  }, { passive: true });
}

function ensureChatThread() {
  let thread = contentArea.querySelector(".chat-thread");
  if (!thread) {
    thread = document.createElement("div");
    thread.className = "chat-thread";
    contentArea.appendChild(thread);
  }
  return thread;
}

function appendUserBubble(text) {
  const thread = ensureChatThread();
  const el = document.createElement("div");
  el.className = "chat-msg chat-msg-user";
  el.innerHTML = `
    <div class="chat-msg-label">You <span class="chat-msg-time">${fmtTime(new Date().toISOString())}</span></div>
    <div class="chat-msg-content">${escapeHtml(text)}</div>`;
  thread.appendChild(el);
  // The user just submitted — always stick to the bottom regardless of
  // their previous scroll position.
  scrollMainToBottom();
}

function showTypingIndicator() {
  const thread = ensureChatThread();
  const el = document.createElement("div");
  el.className = "chat-msg chat-msg-agent chat-msg-typing";
  el.id = "typing-indicator";
  el.innerHTML = `
    <div class="chat-msg-label">Agent</div>
    <div class="typing-dots" aria-label="Agent is thinking"><span></span><span></span><span></span></div>`;
  thread.appendChild(el);
  contentArea.setAttribute("aria-busy", "true");
  maybeScrollToBottom();
  return el;
}

function removeTypingIndicator() {
  const el = document.getElementById("typing-indicator");
  if (el) el.remove();
  contentArea.setAttribute("aria-busy", "false");
}

// ---- Live streaming bubble: rAF-batched token appends ----
let _liveBuffer = "";
let _liveRafScheduled = false;

function ensureLiveAgentBubble() {
  let el = document.getElementById("live-agent-bubble");
  if (el) return el;

  // Prefer to morph the typing indicator in place. This avoids a DOM-level
  // remove/insert flicker when the first token arrives.
  const typing = document.getElementById("typing-indicator");
  if (typing) {
    typing.id = "live-agent-bubble";
    typing.classList.remove("chat-msg-typing");
    typing.innerHTML = `
      <div class="chat-msg-label">Agent <span class="chat-msg-time">${fmtTime(new Date().toISOString())}</span></div>
      <div class="chat-msg-content"><pre class="live-stream"></pre></div>`;
    return typing;
  }

  const thread = ensureChatThread();
  el = document.createElement("div");
  el.className = "chat-msg chat-msg-agent";
  el.id = "live-agent-bubble";
  el.innerHTML = `
    <div class="chat-msg-label">Agent <span class="chat-msg-time">${fmtTime(new Date().toISOString())}</span></div>
    <div class="chat-msg-content"><pre class="live-stream"></pre></div>`;
  thread.appendChild(el);
  maybeScrollToBottom();
  return el;
}

function _flushLiveBuffer() {
  _liveRafScheduled = false;
  if (!_liveBuffer) return;
  const el = ensureLiveAgentBubble();
  const pre = el.querySelector("pre");
  pre.textContent += _liveBuffer;
  _liveBuffer = "";
  maybeScrollToBottom();
}

function appendLiveToken(token) {
  _liveBuffer += token;
  if (!_liveRafScheduled) {
    _liveRafScheduled = true;
    requestAnimationFrame(_flushLiveBuffer);
  }
}

function removeLiveAgentBubble() {
  _liveBuffer = "";
  _liveRafScheduled = false;
  const el = document.getElementById("live-agent-bubble");
  if (el) el.remove();
}

/* -- Input state ---------------------------------------------------------- */

function updateInput() {
  const awaiting = currentConv && (
    currentConv.status === "awaiting_approval"
    || currentConv.status === "awaiting_brd_confirmation"
  );
  messageInput.disabled = awaiting || !selectedId;
  sendBtn.disabled = awaiting || !selectedId || !messageInput.value.trim();
  if (awaiting) {
    messageInput.placeholder = currentConv.status === "awaiting_brd_confirmation"
      ? "Reviewing evidence — confirm or cancel above..."
      : "Awaiting approval...";
  } else if (!selectedId) {
    messageInput.placeholder = "Start a new BRD to begin...";
  } else {
    messageInput.placeholder = "Describe your BRD requirements...";
  }
}

function autoResizeTextarea() {
  messageInput.style.height = "auto";
  const lineHeight = parseFloat(getComputedStyle(messageInput).lineHeight) || 20;
  const maxHeight = lineHeight * TEXTAREA_MAX_ROWS + 20; // padding buffer
  const next = Math.min(messageInput.scrollHeight, maxHeight);
  messageInput.style.height = `${next}px`;
  messageInput.style.overflowY = messageInput.scrollHeight > maxHeight ? "auto" : "hidden";
}

/* -- Data fetching -------------------------------------------------------- */

async function fetchConversations() {
  try {
    conversations = await api.getConversations();
    sidebarLoading = false;
    renderSidebar();
  } catch (err) {
    sidebarLoading = false;
    renderSidebar();
    console.error("Failed to fetch conversations:", err);
  }
}

async function fetchConversation(id) {
  try {
    currentConv = await api.getConversation(id);
    renderContent();
    updateInput();
  } catch (err) {
    console.error("Failed to fetch conversation:", err);
  }
}

async function selectConversation(id) {
  selectedId = id;
  renderSidebar();
  await fetchConversation(id);
  startSidebarPoll();
}

function startSidebarPoll() {
  stopSidebarPoll();
  // Light-weight refresh of the sidebar list so other tabs/users show up.
  sidebarPollTimer = setInterval(fetchConversations, 15000);
}

function stopSidebarPoll() {
  if (sidebarPollTimer) { clearInterval(sidebarPollTimer); sidebarPollTimer = null; }
}

/* -- Mobile sidebar ------------------------------------------------------- */

function openSidebar()  { sidebar.classList.add("open"); backdrop.classList.add("open"); }
function closeSidebar() { sidebar.classList.remove("open"); backdrop.classList.remove("open"); }

menuBtn.addEventListener("click", () => {
  if (sidebar.classList.contains("open")) closeSidebar();
  else openSidebar();
});
backdrop.addEventListener("click", closeSidebar);

/* -- New chat ------------------------------------------------------------- */

newChatBtn.addEventListener("click", async () => {
  try {
    const conv = await api.createConversation();
    selectedId = conv.id;
    currentConv = conv;
    await fetchConversations();
    renderContent();
    updateInput();
    messageInput.focus();
    closeSidebar();
  } catch (err) {
    showToast(err.message);
  }
});

/* -- Welcome hint chips --------------------------------------------------- */

async function useWelcomeHint(hintText) {
  try {
    if (!selectedId) {
      const conv = await api.createConversation();
      selectedId = conv.id;
      currentConv = conv;
      await fetchConversations();
      renderContent();
      updateInput();
    }
    messageInput.value = hintText;
    sendBtn.disabled = !selectedId;
    autoResizeTextarea();
    messageInput.focus();
  } catch (err) {
    showToast(err.message);
  }
}

/* -- Form handling -------------------------------------------------------- */

messageInput.addEventListener("input", () => {
  sendBtn.disabled = !messageInput.value.trim() || !selectedId;
  autoResizeTextarea();
});

messageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    messageForm.requestSubmit();
  }
});

messageForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = messageInput.value.trim();
  if (!text || !selectedId) return;

  const convId = selectedId;
  sendBtn.disabled = true;
  sendBtn.innerHTML = '<span class="spinner"></span> Sending...';

  appendUserBubble(text);
  messageInput.value = "";
  autoResizeTextarea();
  const typing = showTypingIndicator();

  try {
    if (supportsStreaming) {
      await sendViaStreaming(convId, text, typing);
    } else {
      await sendViaRegular(convId, text);
    }
  } catch (err) {
    removeTypingIndicator();
    removeLiveAgentBubble();
    showToast(err.message);
  } finally {
    sendBtn.disabled = !messageInput.value.trim() || !selectedId;
    sendBtn.innerHTML = SEND_BTN_HTML;
  }
});

async function sendViaStreaming(convId, text, typingEl) {
  let gotToken = false;
  let streamError = null;

  await api.sendMessageStream(convId, text, {
    onToken: (token) => {
      gotToken = true;
      appendLiveToken(token);
    },
    onDone: async (conv) => {
      removeLiveAgentBubble();
      removeTypingIndicator();
      if (conv) {
        currentConv = conv;
      } else {
        currentConv = await api.getConversation(convId);
      }
      renderContent();
      updateInput();
      await fetchConversations();
    },
    onError: (msg) => {
      streamError = msg;
    },
  });

  if (streamError && !gotToken) {
    // Streaming unavailable or failed before any tokens — fall back.
    removeTypingIndicator();
    await sendViaRegular(convId, text);
    return;
  }
  if (streamError) {
    throw new Error(streamError);
  }
  typingEl?.remove();
}

async function sendViaRegular(convId, text) {
  const conv = await api.sendMessage(convId, text);
  currentConv = conv;
  removeTypingIndicator();
  removeLiveAgentBubble();
  renderContent();
  updateInput();
  await fetchConversations();
}

/* -- Init ----------------------------------------------------------------- */

initScrollTracking();
fetchConversations();
updateInput();
autoResizeTextarea();

/* -- SSE Log Stream ------------------------------------------------------- */

let logBackoffMs = 1000;
const LOG_BACKOFF_MAX_MS = 30000;

function connectLogStream() {
  const evtSource = new EventSource("/logs/stream");
  evtSource.onopen = () => { logBackoffMs = 1000; };
  evtSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      const line = document.createElement("div");
      line.className = `log-line log-${data.level}`;
      line.textContent = `[${data.level}] ${data.logger}: ${data.message}`;
      logBody.appendChild(line);
      while (logBody.children.length > 200) logBody.removeChild(logBody.firstChild);
      logBody.scrollTop = logBody.scrollHeight;
    } catch { /* ignore malformed */ }
  };
  evtSource.onerror = () => {
    evtSource.close();
    setTimeout(connectLogStream, logBackoffMs);
    logBackoffMs = Math.min(logBackoffMs * 2, LOG_BACKOFF_MAX_MS);
  };
}

if (logToggle) {
  logToggle.addEventListener("click", () => {
    logPanel.classList.toggle("collapsed");
  });
}

connectLogStream();
