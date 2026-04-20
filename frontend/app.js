// frontend/app.js
/**
 * BRD Specialist — Frontend Application
 *
 * Vanilla JS client for the BRD generation workflow.
 */

"use strict";

/* -- API Client ----------------------------------------------------------- */

class ApiClient {
  constructor(baseUrl = "") {
    this.baseUrl = baseUrl;
  }

  async _request(path, options = {}) {
    const res = await fetch(`${this.baseUrl}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed: ${res.status}`);
    }
    if (res.status === 204) return null;
    return res.json();
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
}

const api = new ApiClient();

/* -- State ---------------------------------------------------------------- */

let conversations = [];
let selectedId = null;
let currentConv = null;
let pollTimer = null;

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

/* -- Helpers -------------------------------------------------------------- */

function fmtTime(iso) {
  try { return new Date(iso).toLocaleTimeString(); }
  catch { return iso; }
}

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

function showToast(msg) {
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = `<span>${escapeHtml(msg)}</span><button aria-label="Close">&times;</button>`;
  el.querySelector("button").onclick = () => el.remove();
  toastBox.appendChild(el);
  setTimeout(() => el.remove(), 6000);
}

/* -- Render: sidebar conversation list ------------------------------------ */

function renderSidebar() {
  if (!conversations.length) {
    convList.innerHTML = `
      <div class="empty-state">
        <p class="empty-title">No documents yet</p>
        <p class="empty-sub">Start a new BRD to begin</p>
      </div>`;
    return;
  }

  convList.innerHTML = conversations.map((c) => `
    <div class="conv-item ${c.id === selectedId ? "active" : ""}" data-id="${escapeHtml(c.id)}">
      <div class="conv-item-body">
        <div class="conv-item-title">${escapeHtml(c.title)}</div>
        <div class="conv-item-time">${fmtTime(c.updated_at)}</div>
      </div>
      ${c.status !== "active" ? `<span class="conv-item-warning" title="${escapeHtml(c.status)}">&#9888;</span>` : ""}
      <button class="delete-btn" data-delete="${escapeHtml(c.id)}" title="Delete conversation">&times;</button>
    </div>
  `).join("");

  convList.querySelectorAll(".conv-item").forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.closest(".delete-btn")) return;
      selectConversation(el.dataset.id);
      closeSidebar();
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

/* -- BRD formatting helpers ------------------------------------------------ */

const BRD_HEADINGS = [
  "Problem Statement",
  "Scope and Exclusions",
  "Functional Requirements",
  "Assumptions and Constraints",
  "Risks and Open Questions",
];

function formatEvidenceSummary(text) {
  const escaped = escapeHtml(text);
  // Split on numbered headings like "1. Data Source" or "## Data Source"
  const parts = escaped.split(/(?:^|\n)(?:\d+\.\s+|#{1,3}\s+)(.+?)(?:\n|$)/);
  if (parts.length <= 1) {
    return `<div class="brd-evidence-section"><div class="brd-evidence-text">${escaped}</div></div>`;
  }

  let html = "";
  // First part before any heading
  const preamble = parts[0].trim();
  if (preamble) {
    html += `<div class="brd-evidence-section"><div class="brd-evidence-text">${preamble}</div></div>`;
  }
  // Pairs of [heading, body]
  for (let i = 1; i < parts.length; i += 2) {
    const label = parts[i] || "";
    const body = (parts[i + 1] || "").trim();
    html += `<div class="brd-evidence-section">`;
    html += `<div class="brd-evidence-label">${label}</div>`;
    if (body) html += `<div class="brd-evidence-text">${body}</div>`;
    html += `</div>`;
  }
  return html;
}

function isBrdDocument(text) {
  const lower = text.toLowerCase();
  let matches = 0;
  for (const h of BRD_HEADINGS) {
    if (lower.includes(h.toLowerCase())) matches++;
  }
  return matches >= 3;
}

function formatBrdDocument(text) {
  let html = escapeHtml(text);
  // Convert numbered headings or markdown headings to <h3>
  html = html.replace(/(?:^|\n)(?:#{1,3}\s+)?(\d+\.\s+(?:Problem Statement|Scope and Exclusions|Functional Requirements|Assumptions and Constraints|Risks and Open Questions))/gi, "\n<h3>$1</h3>");
  // Convert **bold** to <strong>
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  // Convert bullet lines to list items
  html = html.replace(/(?:^|\n)[-*]\s+(.+)/g, "\n<li>$1</li>");
  // Wrap consecutive <li> in <ul>
  html = html.replace(/((?:<li>.+?<\/li>\n?)+)/g, "<ul>$1</ul>");
  // Wrap remaining lines in <p> (skip tags and empty lines)
  html = html.split("\n").map((line) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("<")) return line;
    return `<p>${trimmed}</p>`;
  }).join("\n");
  return html;
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
          <span class="welcome-hint">Fetch records and draft a BRD</span>
          <span class="welcome-hint">Analyse data and create requirements</span>
          <span class="welcome-hint">Review evidence and generate docs</span>
        </div>
      </div>`;
    return;
  }

  const c = currentConv;
  let html = "";

  // Messages
  if (c.messages && c.messages.length) {
    html += `<div class="chat-thread">`;
    for (const msg of c.messages) {
      const isUser = msg.role === "user";
      const isBrd = !isUser && isBrdDocument(msg.content);
      if (isBrd) {
        html += `
          <div class="chat-msg chat-msg-agent">
            <div class="chat-msg-label">Agent <span class="chat-msg-time">${fmtTime(msg.timestamp)}</span></div>
            <div class="brd-document">
              <div class="brd-document-header">
                <span class="brd-document-badge">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                  BRD
                </span>
                <span class="brd-document-label">Business Requirements Document</span>
              </div>
              <div class="brd-document-body">${formatBrdDocument(msg.content)}</div>
            </div>
          </div>`;
      } else {
        html += `
          <div class="chat-msg ${isUser ? "chat-msg-user" : "chat-msg-agent"}">
            <div class="chat-msg-label">${isUser ? "You" : "Agent"} <span class="chat-msg-time">${fmtTime(msg.timestamp)}</span></div>
            <div class="chat-msg-content">${isUser ? escapeHtml(msg.content) : "<pre>" + escapeHtml(msg.content) + "</pre>"}</div>
          </div>`;
      }
    }
    html += `</div>`;
  }

  // Approval dialog
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

  // Activity log
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

  // Wire approval buttons
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

  // Wire activity toggle
  const actToggle = $("#activity-toggle");
  if (actToggle) {
    actToggle.addEventListener("click", () => {
      const body = $("#activity-body");
      const btn = actToggle.querySelector(".activity-toggle");
      body.classList.toggle("collapsed");
      btn.textContent = body.classList.contains("collapsed") ? "Show" : "Hide";
    });
  }

  // Auto-scroll to bottom
  const mainScroll = $("#main-scroll");
  mainScroll.scrollTop = mainScroll.scrollHeight;
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

/* -- Data fetching -------------------------------------------------------- */

async function fetchConversations() {
  try {
    conversations = await api.getConversations();
    renderSidebar();
  } catch (err) {
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
}

function startPoll() {
  stopPoll();
  pollTimer = setInterval(async () => {
    if (selectedId) await fetchConversation(selectedId);
  }, 3000);
}

function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

/* -- Mobile sidebar ------------------------------------------------------- */

function openSidebar()  { sidebar.classList.add("open"); backdrop.classList.add("open"); }
function closeSidebar() { sidebar.classList.remove("open"); backdrop.classList.remove("open"); }

menuBtn.addEventListener("click", () => {
  sidebar.classList.contains("open") ? closeSidebar() : openSidebar();
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

/* -- Form handling -------------------------------------------------------- */

messageInput.addEventListener("input", () => {
  sendBtn.disabled = !messageInput.value.trim() || !selectedId;
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

  sendBtn.disabled = true;
  sendBtn.innerHTML = '<span class="spinner"></span> Sending...';

  try {
    currentConv = await api.sendMessage(selectedId, text);
    messageInput.value = "";
    renderContent();
    updateInput();
    await fetchConversations();
  } catch (err) {
    showToast(err.message);
  } finally {
    sendBtn.disabled = !messageInput.value.trim() || !selectedId;
    sendBtn.innerHTML = `
      <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
      </svg> Send`;
  }
});

/* -- Init ----------------------------------------------------------------- */

fetchConversations();
updateInput();

/* -- SSE Log Stream ------------------------------------------------------- */

function connectLogStream() {
  const evtSource = new EventSource("/logs/stream");
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
    setTimeout(connectLogStream, 3000);
  };
}

if (logToggle) {
  logToggle.addEventListener("click", () => {
    logPanel.classList.toggle("collapsed");
  });
}

connectLogStream();
