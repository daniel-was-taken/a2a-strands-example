/**
 * A2A Database Orchestrator — Frontend Application
 *
 * Vanilla JS client for the orchestrator REST API.
 * All API interaction goes through the ApiClient class so the
 * base URL / headers can be swapped for a different backend.
 */

"use strict";

/* ── API Client ──────────────────────────────────────────────────────── */

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
    return res.json();
  }

  healthCheck()            { return this._request("/health"); }
  submitQuery(query)       { return this._request("/query", { method: "POST", body: JSON.stringify({ query }) }); }
  getQueries()             { return this._request("/queries"); }
  getQuery(id)             { return this._request(`/queries/${encodeURIComponent(id)}`); }
  approveQuery(id)         { return this._request(`/queries/${encodeURIComponent(id)}/approve`, { method: "POST" }); }
  rejectQuery(id)          { return this._request(`/queries/${encodeURIComponent(id)}/reject`,  { method: "POST" }); }
}

const api = new ApiClient();

/* ── State ───────────────────────────────────────────────────────────── */

let queries = [];
let selectedId = null;
let pollTimer = null;
let detailTimer = null;

/* ── DOM refs ────────────────────────────────────────────────────────── */

const $ = (sel) => document.querySelector(sel);
const sidebar      = $("#sidebar");
const backdrop     = $("#backdrop");
const menuBtn      = $("#menu-btn");
const queryList    = $("#query-list");
const contentArea  = $("#content-area");
const queryForm    = $("#query-form");
const queryInput   = $("#query-input");
const submitBtn    = $("#submit-btn");
const toastBox     = $("#toast-container");

/* ── Helpers ─────────────────────────────────────────────────────────── */

const STATUS_LABELS = {
  COMPLETED: "Completed",
  PENDING_APPROVAL: "Pending Approval",
  RECOMMENDED_REJECT: "Recommended Reject",
  REJECTED: "Rejected",
  FAILED: "Failed",
};

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

/* ── Render: sidebar query list ──────────────────────────────────────── */

function renderQueryList() {
  if (!queries.length) {
    queryList.innerHTML = `
      <div class="empty-state">
        <p class="empty-title">No queries yet</p>
        <p class="empty-sub">Submit a query to get started</p>
      </div>`;
    return;
  }

  queryList.innerHTML = queries.map((q) => `
    <button class="query-item ${q.request_id === selectedId ? "active" : ""}"
            data-id="${escapeHtml(q.request_id)}">
      <div class="query-item-top">
        <span class="query-item-text">${escapeHtml(q.query)}</span>
        <span class="badge badge-${q.status}">${STATUS_LABELS[q.status] || q.status}</span>
      </div>
      <div class="query-item-time">${fmtTime(q.created_at)}</div>
    </button>
  `).join("");

  queryList.querySelectorAll(".query-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectedId = btn.dataset.id;
      renderQueryList();
      renderDetail();
      closeSidebar();
      startDetailPoll();
    });
  });
}

/* ── Render: main content area ───────────────────────────────────────── */

function renderDetail() {
  const q = queries.find((q) => q.request_id === selectedId);
  if (!q) {
    contentArea.innerHTML = `
      <div class="welcome">
        <svg class="welcome-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>
        </svg>
        <h2>A2A Database Orchestrator</h2>
        <p>Submit a query below or select one from the sidebar</p>
      </div>`;
    return;
  }

  let html = `<div class="result-card">`;

  // Header
  html += `
    <div class="result-header">
      <div>
        <div class="result-query">${escapeHtml(q.query)}</div>
        <div class="result-id">${escapeHtml(q.request_id.slice(0, 8))}…</div>
      </div>
      <span class="badge badge-${q.status}">${STATUS_LABELS[q.status] || q.status}</span>
    </div>`;

  // Approval dialog
  if (q.status === "PENDING_APPROVAL" && q.review_verdict) {
    html += `
      <div class="approval-box">
        <h3>Human Approval Required</h3>
        <p>The safety reviewer approved this destructive query, but it requires your confirmation before execution.</p>
        <div class="approval-verdict">${escapeHtml(q.review_verdict)}</div>
        <div class="approval-actions">
          <button class="btn-approve" data-action="approve" data-id="${escapeHtml(q.request_id)}">
            &#10003; Approve &amp; Execute
          </button>
          <button class="btn-reject" data-action="reject" data-id="${escapeHtml(q.request_id)}">
            &#10007; Reject
          </button>
        </div>
      </div>`;
  }

  // Result body
  if (q.result && q.status !== "PENDING_APPROVAL") {
    html += `<div class="result-body"><pre>${escapeHtml(q.result)}</pre></div>`;
  }

  // Verdict (when not pending)
  if (q.review_verdict && q.status !== "PENDING_APPROVAL") {
    html += `<div class="result-verdict">Safety verdict: ${escapeHtml(q.review_verdict)}</div>`;
  }

  // Activity log
  if (q.events && q.events.length) {
    html += `
      <div class="activity-log">
        <div class="activity-title">Agent Activity</div>
        <ul class="activity-list">
          ${q.events.map((e) => `
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
      </div>`;
  }

  html += `</div>`;
  contentArea.innerHTML = html;

  // Wire approval buttons
  contentArea.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const action = btn.dataset.action;
      const id = btn.dataset.id;
      try {
        if (action === "approve") await api.approveQuery(id);
        else                      await api.rejectQuery(id);
        await fetchQueries();
        renderDetail();
      } catch (err) {
        showToast(err.message);
      }
    });
  });
}

/* ── Data fetching ───────────────────────────────────────────────────── */

async function fetchQueries() {
  try {
    queries = await api.getQueries();
    renderQueryList();
    // Update detail if selected
    if (selectedId) renderDetail();
  } catch (err) {
    console.error("Failed to fetch queries:", err);
  }
}

async function fetchDetail() {
  if (!selectedId) return;
  try {
    const q = await api.getQuery(selectedId);
    // Replace in local array
    const idx = queries.findIndex((x) => x.request_id === selectedId);
    if (idx >= 0) queries[idx] = q;
    else queries.unshift(q);
    renderQueryList();
    renderDetail();
    // Stop polling if terminal
    if (["COMPLETED", "REJECTED", "FAILED"].includes(q.status)) {
      stopDetailPoll();
    }
  } catch { /* ignore transient */ }
}

function startPoll() {
  stopPoll();
  pollTimer = setInterval(fetchQueries, 4000);
}

function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function startDetailPoll() {
  stopDetailPoll();
  detailTimer = setInterval(fetchDetail, 2000);
}

function stopDetailPoll() {
  if (detailTimer) { clearInterval(detailTimer); detailTimer = null; }
}

/* ── Mobile sidebar ──────────────────────────────────────────────────── */

function openSidebar()  { sidebar.classList.add("open"); backdrop.classList.add("open"); }
function closeSidebar() { sidebar.classList.remove("open"); backdrop.classList.remove("open"); }

menuBtn.addEventListener("click", () => {
  sidebar.classList.contains("open") ? closeSidebar() : openSidebar();
});
backdrop.addEventListener("click", closeSidebar);

/* ── Form handling ───────────────────────────────────────────────────── */

queryInput.addEventListener("input", () => {
  submitBtn.disabled = !queryInput.value.trim();
});

queryInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    queryForm.requestSubmit();
  }
});

queryForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = queryInput.value.trim();
  if (!text) return;

  submitBtn.disabled = true;
  submitBtn.innerHTML = '<span class="spinner"></span> Sending…';

  try {
    const res = await api.submitQuery(text);
    selectedId = res.request_id;
    queryInput.value = "";
    await fetchQueries();
    renderDetail();
    startDetailPoll();
  } catch (err) {
    showToast(err.message);
  } finally {
    submitBtn.disabled = !queryInput.value.trim();
    submitBtn.innerHTML = `
      <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
      </svg> Send`;
  }
});

/* ── Init ────────────────────────────────────────────────────────────── */

fetchQueries();
startPoll();
