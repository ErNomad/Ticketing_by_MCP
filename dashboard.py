"""Interactive web dashboard for the MCP ticket-triage demonstration."""

import asyncio
import logging
import threading
from copy import deepcopy

from flask import Flask, jsonify, render_template_string, request

import tools
from agents import CONFIDENCE_THRESHOLD, triage
from client import MCPHub

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024
logger = logging.getLogger(__name__)
_state_lock = threading.RLock()


def _sample_tickets():
    return [
        {
            "id": ticket_id,
            "customer": customer,
            "text": text,
            "category": None,
            "priority": None,
            "status": "new",
            "handled_by": None,
        }
        for ticket_id, (customer, text, _) in enumerate(tools.SEED_TICKETS, 1)
    ]


_state = {
    "status": "idle",
    "tickets": _sample_tickets(),
    "events": [],
    "next_event_id": 1,
    "running_ticket_id": None,
    "last_ticket_id": None,
    "error": None,
}


def _append_event(event):
    event = deepcopy(event)
    event["id"] = _state["next_event_id"]
    _state["next_event_id"] += 1
    _state["events"].append(event)


def _record_mcp_event(event):
    with _state_lock:
        ticket_id = event.get("ticket_id")
        if event["type"] == "agent":
            _append_event(event)
            return

        if event.get("phase") == "response" and event["tool"] == "update_ticket":
            result = event.get("result", {})
            if not result.get("error"):
                for ticket in _state["tickets"]:
                    if ticket["id"] == ticket_id:
                        ticket.update(result)
                        break
        _append_event(event)


async def _run_ticket(ticket_id):
    async with MCPHub(on_event=_record_mcp_event) as hub:
        await triage(hub, ticket_id)


def _run_demo(ticket_id):
    try:
        asyncio.run(_run_ticket(ticket_id))
    except Exception as error:
        logger.exception("Ticket demo run failed")
        with _state_lock:
            _state["status"] = "failed"
            _state["running_ticket_id"] = None
            _state["error"] = str(error)
            for ticket in _state["tickets"]:
                if ticket["id"] == ticket_id:
                    ticket["status"] = "failed"
                    break
            _append_event({"type": "error", "detail": str(error)})
        return

    with _state_lock:
        _state["running_ticket_id"] = None
        _state["last_ticket_id"] = ticket_id
        all_finished = all(ticket["status"] in ("resolved", "escalated")
                           for ticket in _state["tickets"])
        _state["status"] = "completed" if all_finished else "idle"
        _append_event({
            "type": "complete",
            "ticket_id": ticket_id,
            "detail": f"Ticket #{ticket_id} has been processed.",
        })


PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#101522">
  <title>Ticket Triage · MCP Demo</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0c111b; --panel: #151d2b; --panel-raised: #1b2637;
      --line: #2b3a50; --text: #edf3fc; --muted: #9aabc2;
      --blue: #70a7ff; --green: #67d7a1; --orange: #ffba68; --red: #ff8585;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; background:
        radial-gradient(ellipse at 70% -20%, #263c62 0, transparent 48%), var(--bg);
      color: var(--text); font: 15px/1.5 system-ui, sans-serif;
    }
    main { width: min(1120px, calc(100% - 36px)); margin: 0 auto; padding: 48px 0 72px; }
    h1, h2, p { margin-top: 0; }
    h1 { margin-bottom: 8px; font-size: clamp(2rem, 5vw, 3.2rem); letter-spacing: -.04em; }
    h2 { margin-bottom: 6px; font-size: 1.2rem; }
    .eyebrow { color: var(--blue); font-size: .78rem; font-weight: 750; letter-spacing: .13em; text-transform: uppercase; }
    .intro { max-width: 720px; margin-bottom: 26px; color: var(--muted); }
    .toolbar { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin: 24px 0 30px; }
    #reset-all { margin-left: auto; }
    #reset-all[hidden] { display: none; }
    button {
      border: 0; border-radius: 9px; padding: 12px 19px; background: var(--blue);
      color: #0b1422; font: inherit; font-weight: 750; cursor: pointer;
      transition: transform .18s ease, filter .18s ease;
    }
    button:hover:not(:disabled) { transform: translateY(-2px); filter: brightness(1.08); }
    button:disabled { opacity: .6; cursor: wait; }
    #run-status { color: var(--muted); }
    .panel { border: 1px solid var(--line); border-radius: 14px; background: #111a28e8; }
    .flow-panel { padding: 22px; margin-bottom: 24px; overflow: hidden; }
    .flow-layout { position: relative; display: grid; grid-template-columns: minmax(210px, .85fr) minmax(320px, 1.45fr) minmax(220px, .9fr); gap: 22px; align-items: start; }
    .agent-mcp-connections { position: absolute; inset: 0; z-index: 1; width: 100%; height: 100%; overflow: visible; pointer-events: none; }
    .agent-mcp-connection { fill: none; stroke: var(--line); stroke-width: 2; marker-end: url(#agent-mcp-arrow); transition: stroke .2s ease, filter .2s ease; }
    .agent-mcp-connection.active { stroke: var(--green); filter: drop-shadow(0 0 5px var(--green)); }
    .ticket-picker { min-width: 0; }
    .ticket-picker .section-head { margin: 0 0 12px; }
    #tickets { display: grid; gap: 10px; max-height: 700px; overflow: auto; padding-right: 4px; }
    .flow-main { min-width: 0; }
    .flow-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
    .flow-heading p { margin: 0; color: var(--muted); font-size: .85rem; }
    .flow { display: flex; flex-direction: column; align-items: stretch; gap: 8px; margin: 22px auto 0; }
    .node {
      width: 100%; min-height: 70px; display: grid; place-content: center; gap: 3px; text-align: center;
      border: 1px solid var(--line); border-radius: 11px; background: var(--panel);
      transition: border-color .2s ease, box-shadow .2s ease, transform .2s ease;
    }
    .node strong { font-size: .95rem; }
    .node small { color: var(--muted); font-size: .76rem; }
    .node.mcp { border-color: #3b70a5; background: #14263a; }
    .node.active { border-color: var(--blue); box-shadow: 0 0 22px #70a7ff55; transform: translateY(-2px); }
    .flow-arrow { position: relative; height: 24px; color: var(--line); text-align: center; font-size: 1.65rem; line-height: 1; transition: color .2s ease, filter .2s ease; }
    .flow-arrow.active { color: var(--green); filter: drop-shadow(0 0 7px var(--green)); animation: arrow-pulse .65s ease-in-out infinite alternate; }
    .flow-arrow.active::after { position: absolute; top: 0; left: calc(50% - 3px); width: 6px; height: 6px; border-radius: 50%; content: ""; background: var(--green); box-shadow: 0 0 8px var(--green); animation: down-packet .65s ease-in-out infinite alternate; }
    @keyframes arrow-pulse { to { transform: scale(1.25); } }
    @keyframes down-packet { to { top: 100%; } }
    .mcp-current-tool { min-height: 1.2em; margin: 6px 0 0; color: var(--muted); font-size: .73rem; text-align: center; overflow-wrap: anywhere; }
    .decision-split { position: relative; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 8px; padding-top: 22px; }
    .decision-split::before { position: absolute; top: 0; left: 25%; right: 25%; border-top: 1px solid var(--line); content: ""; }
    .decision-path { position: relative; display: grid; align-content: start; gap: 7px; padding: 10px; border: 1px solid var(--line); border-radius: 10px; background: #101927; transition: border-color .2s ease, box-shadow .2s ease, background .2s ease; }
    .decision-path::before { position: absolute; top: -22px; left: 50%; height: 22px; border-left: 1px solid var(--line); content: ""; }
    .decision-path.selected { border-color: var(--green); box-shadow: 0 0 12px #67d7a133; background: #14251f; }
    .decision-path.not-selected { border-color: var(--red); box-shadow: 0 0 12px #ff858533; background: #26191e; }
    .path-label { color: var(--text); font-size: .76rem; font-weight: 700; text-align: center; }
    .path-note { color: var(--muted); font-size: .7rem; text-align: center; }
    .path-note.active { color: var(--green); }
    .kb-node { min-height: 105px; }
    .kb-match { color: var(--muted); font-size: .76rem; }
    .kb-confidence { color: var(--blue); font-size: .8rem; font-weight: 700; }
    .route-result { padding: 6px; border: 1px solid var(--line); border-radius: 7px; color: var(--muted); font-size: .68rem; text-align: center; }
    .route-result.selected { border-color: var(--green); color: var(--green); }
    .route-result.not-selected { border-color: var(--red); color: var(--red); }
    .shared-tools { min-width: 0; }
    .shared-tools h2 { margin-bottom: 4px; }
    .shared-tools > p { margin: 0 0 10px; color: var(--muted); font-size: .8rem; }
    .mcp-server { margin-top: 210px; padding: 14px; }
    .mcp-server > strong { display: block; text-align: center; }
    .tool-branches { display: grid; gap: 7px; width: 100%; margin-top: 8px; }
    .tool-branch { display: grid; grid-template-columns: minmax(0, 1fr); color: var(--line); transition: color .2s ease, filter .2s ease; }
    .tool-branch.active { color: var(--green); filter: drop-shadow(0 0 6px #67d7a166); }
    .tool-block { padding: 7px 9px; border: 1px solid var(--line); border-radius: 8px; color: var(--muted); background: var(--panel); font-size: .76rem; text-align: center; transition: border-color .2s ease, color .2s ease, background .2s ease; }
    .tool-branch.active .tool-block { border-color: var(--green); color: var(--text); background: #193329; }
    .tool-options { display: grid; gap: 4px; margin-top: 6px; }
    .tool-option { padding: 4px 6px; border: 1px solid var(--line); border-radius: 6px; color: var(--muted); font-size: .67rem; text-align: center; }
    .tool-option.correct { border-color: var(--green); color: var(--green); background: #193329; }
    .tool-option.incorrect { border-color: var(--red); color: var(--red); background: #321b25; }
    .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }
    .stat { padding: 15px 17px; }
    .stat strong { display: block; font-size: 1.65rem; line-height: 1.2; }
    .stat span { color: var(--muted); font-size: .82rem; }
    .columns { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; align-items: start; }
    .section-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 12px; }
    .ticket { padding: 16px 18px; transition: border-color .25s ease, background .25s ease; }
    .ticket.updated { border-color: #5783b6; background: #172539; }
    .ticket-top { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
    .ticket-name { font-weight: 720; }
    .ticket-id, .meta { color: var(--muted); font-size: .82rem; }
    .ticket p { margin: 10px 0 0; color: #c9d5e5; }
    .ticket-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 13px; }
    .category-label { color: var(--muted); font-size: .8rem; }
    .category-value { color: var(--blue); font-weight: 700; }
    .ticket-button { padding: 8px 13px; font-size: .83rem; }
    .ticket-button:disabled { cursor: default; }
    .badge { display: inline-block; border-radius: 99px; padding: 2px 9px; font-size: .73rem; font-weight: 700; background: #283548; }
    .badge.new { color: var(--muted); }
    .badge.classified, .badge.answered { color: var(--blue); background: #203552; }
    .badge.resolved { color: var(--green); background: #15362d; }
    .badge.escalated { color: var(--orange); background: #3b2b1d; }
    .activity-panel { max-height: 690px; padding: 18px; overflow: auto; }
    #activity { display: grid; gap: 9px; }
    .event { border-left: 2px solid var(--line); padding: 4px 0 4px 11px; animation: appear .24s ease both; }
    .event.agent { border-color: var(--green); }
    .event.tool { border-color: var(--blue); }
    .event.error { border-color: var(--red); }
    .event-title { font-size: .83rem; font-weight: 700; }
    .event-detail { margin-top: 2px; color: var(--muted); font-size: .77rem; overflow-wrap: anywhere; white-space: pre-wrap; }
    .event-meta { color: var(--muted); font-size: .7rem; }
    @keyframes appear { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: none; } }
    .footnote { margin-top: 24px; color: var(--muted); font-size: .79rem; }
    .error-banner { display: none; margin: 0 0 18px; padding: 12px 15px; border: 1px solid #733d48; border-radius: 9px; color: #ffc0c0; background: #321b25; }
    @media (max-width: 900px) {
      .columns { grid-template-columns: 1fr; }
      .flow-layout { grid-template-columns: 1fr; }
      .agent-mcp-connections { display: none; }
      .shared-tools { max-width: 560px; margin: 0 auto; width: 100%; }
      .mcp-server { margin-top: 0; }
      #tickets { max-height: none; }
      .activity-panel { max-height: 420px; }
    }
    @media (max-width: 620px) {
      main { width: min(100% - 24px, 1120px); padding-top: 30px; }
      .flow-panel { padding: 16px; }
      .decision-split { gap: 6px; }
      .decision-path { padding: 7px; }
      .stats { grid-template-columns: repeat(2, 1fr); }
      .flow-heading { display: block; }
      .flow-heading p { margin-top: 4px; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { scroll-behavior: auto !important; animation-duration: .01ms !important; transition-duration: .01ms !important; }
    }
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Interactive MCP walkthrough</div>
    <h1>Ticket triage, agent by agent.</h1>
    <p class="intro">Choose one ticket to start. Follow it through the classifier, responder, knowledge base, and escalation flow while the MCP server routes real tool calls to the right category.</p>
  </header>
  <div class="toolbar">
    <span id="run-status" role="status" aria-live="polite">Choose a ticket to begin.</span>
    <button id="reset-all" type="button" hidden>Reset all</button>
  </div>
  <div id="error-banner" class="error-banner" role="alert"></div>
  <section class="panel flow-panel" aria-label="Tickets, agent flow, and shared MCP server">
    <div class="flow-layout">
      <svg id="agent-mcp-connections" class="agent-mcp-connections" aria-hidden="true" focusable="false">
        <defs>
          <marker id="agent-mcp-arrow" viewBox="0 0 8 8" refX="7" refY="4"
                  markerWidth="7" markerHeight="7" orient="auto" markerUnits="userSpaceOnUse">
            <path d="M 0 0 L 8 4 L 0 8 z" fill="context-stroke"></path>
          </marker>
        </defs>
        <path id="connection-classifier-mcp" class="agent-mcp-connection"></path>
      </svg>
      <section class="ticket-picker" aria-label="Sample tickets">
        <div class="section-head"><h2>Tickets</h2><span class="meta">Start one at a time</span></div>
        <div id="tickets" aria-live="polite"></div>
      </section>
      <div class="flow-main">
        <div class="flow-heading">
          <h2>Follow the active ticket</h2>
          <p>See the lookup, confidence check, and possible outcomes.</p>
        </div>
        <div class="flow">
          <div id="node-customer" class="node"><strong>Customer ticket</strong><small>Starts on click</small></div>
          <div id="arrow-ticket-classifier" class="flow-arrow" data-stage="ticket-classifier" aria-hidden="true">↓</div>
          <div id="node-classifier" class="node"><strong>Classifier</strong><small>Finds category and priority</small></div>
          <div id="arrow-classifier-responder" class="flow-arrow" data-stage="classifier-responder" aria-hidden="true">↓</div>
          <div>
            <div id="node-responder" class="node"><strong>Responder</strong><small>Searches for guidance via MCP</small></div>
          </div>
          <div id="arrow-responder-split" class="flow-arrow" aria-hidden="true">↓</div>
          <div class="decision-split" aria-label="Responder routes">
            <div id="route-knowledge" class="decision-path">
              <strong class="path-label">Knowledge Base</strong>
              <small id="arrow-responder-knowledge-base" class="path-note" data-stage="responder-knowledge-base">MCP search tool</small>
              <div id="node-knowledge-base" class="node kb-node">
                <strong>Search result</strong>
                <span id="kb-match" class="kb-match">Waiting for search</span>
                <span id="kb-confidence" class="kb-confidence" data-threshold="{{ confidence_threshold }}" role="status" aria-live="polite">Match score: — · cutoff: {{ confidence_threshold }}</span>
                <small>Rule-based keyword score, not a probability</small>
              </div>
              <div id="route-resolution" class="route-result">Suitable match + customer confirms → resolved</div>
            </div>
            <div id="route-escalation" class="decision-path">
              <strong class="path-label">Escalation · only if needed</strong>
              <small id="arrow-responder-escalation" class="path-note" data-stage="responder-escalation">Low score or the customer says the fix failed</small>
              <div id="node-escalation" class="node"><strong>Escalation agent</strong><small>Routes the ticket to the appropriate team via MCP</small></div>
              <div class="route-result">Ticket routed to the appropriate support team</div>
            </div>
          </div>
        </div>
      </div>
      <aside class="shared-tools" aria-label="Shared MCP server and tool categories">
        <div class="section-head"><h2>Shared MCP server</h2></div>
        <p>Green is the selected tool; red marks an incompatible team tool.</p>
        <div id="node-mcp" class="node mcp-server"><strong>MCP server</strong></div>
        <div id="mcp-current-tool" class="mcp-current-tool" aria-live="polite">Waiting for a tool call</div>
        <div class="tool-branches" aria-label="MCP tool categories">
          <div class="tool-branch" data-category="Ticketing"><div class="tool-block">Ticketing tools</div></div>
          <div class="tool-branch" data-category="Knowledge Base"><div class="tool-block">Knowledge Base · search_kb</div></div>
          <div class="tool-branch" data-category="Escalations">
            <div class="tool-block">
              Escalation tools
              <div class="tool-options" aria-label="Escalation team tools">
                <span class="tool-option" data-tool="escalate_to_it_support">IT support</span>
                <span class="tool-option" data-tool="escalate_to_billing_team">Billing team</span>
                <span class="tool-option" data-tool="escalate_to_security_team">Security team</span>
              </div>
            </div>
          </div>
          <div class="tool-branch" data-category="Audit"><div class="tool-block">Audit tools</div></div>
        </div>
      </aside>
    </div>
  </section>
  <section class="stats" aria-label="Ticket totals">
    <div class="panel stat"><strong id="stat-total">5</strong><span>Sample tickets</span></div>
    <div class="panel stat"><strong id="stat-resolved">0</strong><span>Resolved</span></div>
    <div class="panel stat"><strong id="stat-escalated">0</strong><span>Escalated</span></div>
    <div class="panel stat"><strong id="stat-tools">0</strong><span>MCP calls</span></div>
  </section>
  <div class="columns">
    <section>
      <div class="section-head"><h2>Live activity</h2><span class="meta">Agent messages and MCP traffic</span></div>
      <div class="panel activity-panel" aria-live="polite"><div id="activity"></div></div>
    </section>
  </div>
  <p class="footnote">This is a public, sample-data-only demonstration. Ticket and activity data live in memory and reset when the service restarts. It is not a real support system.</p>
</main>
<script>
  const ticketsElement = document.getElementById("tickets");
  const activityElement = document.getElementById("activity");
  const statusElement = document.getElementById("run-status");
  const resetButton = document.getElementById("reset-all");
  const errorBanner = document.getElementById("error-banner");
  const confidenceThreshold = Number(document.getElementById("kb-confidence").dataset.threshold);
  const nodeIds = {Classifier: "node-classifier", Responder: "node-responder", Escalation: "node-escalation"};
  const stageArrows = {
    Classifier: "arrow-ticket-classifier",
    Responder: "arrow-classifier-responder",
    Escalation: "arrow-responder-escalation"
  };
  let eventCursor = 0;
  let initialStateLoaded = false;
  const eventQueue = [];
  let playingEvents = false;
  let running = false;
  let toolCategoryFlash = 0;
  let activeNodeId = null;
  let selectedEscalationTool = null;
  let activeTicketPlaybackId = null;
  let latestState = null;

  function makeElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function renderTickets(tickets) {
    ticketsElement.replaceChildren();
    for (const ticket of tickets) {
      const displayStatus = ticket.id === activeTicketPlaybackId ? "processing" : ticket.status;
      const card = makeElement("article", "panel ticket");
      const top = makeElement("div", "ticket-top");
      top.append(
        makeElement("span", "ticket-id", `#${ticket.id}`),
        makeElement("span", "ticket-name", ticket.customer),
        makeElement("span", `badge ${displayStatus}`, displayStatus),
        makeElement("span", "meta", ticket.priority || "Priority pending")
      );
      const actions = makeElement("div", "ticket-actions");
      const category = makeElement("span", "category-label");
      category.append(
        document.createTextNode("Category: "),
        makeElement("strong", "category-value", ticket.category || "Not classified")
      );
      const startButton = makeElement(
        "button",
        "ticket-button",
        displayStatus === "resolved" || displayStatus === "escalated"
          ? "Processed"
          : displayStatus === "processing"
            ? "Processing…"
            : displayStatus === "failed"
              ? "Retry ticket"
              : "Start ticket"
      );
      startButton.type = "button";
      startButton.dataset.ticketId = ticket.id;
      startButton.disabled = running
        || displayStatus === "resolved"
        || displayStatus === "escalated"
        || displayStatus === "processing";
      actions.append(category, startButton);
      card.append(top, makeElement("p", "", ticket.text), actions);
      ticketsElement.append(card);
    }
  }

  function compactResult(result) {
    if (!result || typeof result !== "object") return "";
    if (result.article_id) return `${result.article_id} · confidence ${Number(result.confidence).toFixed(2)}`;
    if (result.team) return `${result.team}${result.reference ? ` · ${result.reference}` : ""}`;
    if (result.status) return `Ticket status: ${result.status}`;
    if (Array.isArray(result)) return `${result.length} ticket(s) returned`;
    if (result.feedback !== undefined) return "Customer feedback received";
    if (result.ok) return "Recorded";
    return result.error || "";
  }

  function flashElement(element) {
    if (!element) return;
    element.classList.add("active");
    window.setTimeout(() => element.classList.remove("active"), 900);
  }

  function highlightNode(agent) {
    const id = nodeIds[agent];
    if (activeNodeId && activeNodeId !== id) {
      document.getElementById(activeNodeId).classList.remove("active");
    }
    activeNodeId = id || null;
    if (activeNodeId) document.getElementById(activeNodeId).classList.add("active");
    document.getElementById("connection-classifier-mcp").classList.toggle("active", agent === "Classifier");
  }

  function updateMcpConnections() {
    const svg = document.getElementById("agent-mcp-connections");
    if (!svg.getClientRects().length) return;
    const layout = document.querySelector(".flow-layout");
    const layoutRect = layout.getBoundingClientRect();
    const mcpRect = document.getElementById("node-mcp").getBoundingClientRect();
    const sources = [["connection-classifier-mcp", "node-classifier"]];
    svg.setAttribute("viewBox", `0 0 ${layoutRect.width} ${layoutRect.height}`);
    for (const [connectionId, sourceId] of sources) {
      const sourceRect = document.getElementById(sourceId).getBoundingClientRect();
      const startX = sourceRect.right - layoutRect.left;
      const startY = sourceRect.top + sourceRect.height / 2 - layoutRect.top;
      const endX = mcpRect.left + mcpRect.width / 2 - layoutRect.left;
      const endY = mcpRect.top - layoutRect.top;
      document.getElementById(connectionId).setAttribute(
        "d", `M ${startX} ${startY} H ${endX} V ${endY}`
      );
    }
  }

  function highlightEscalationTool(tool) {
    if (tool && tool.startsWith("escalate_to_")) selectedEscalationTool = tool;
    for (const option of document.querySelectorAll(".tool-option")) {
      option.classList.toggle("correct", option.dataset.tool === selectedEscalationTool);
      option.classList.toggle("incorrect", Boolean(selectedEscalationTool)
        && option.dataset.tool !== selectedEscalationTool);
    }
  }

  function pulseToolCategory(category, tool = null, agent = null) {
    const branches = document.querySelectorAll(".tool-branch");
    branches.forEach(branch => branch.classList.remove("active"));
    const flash = ++toolCategoryFlash;
    if (!category) {
      document.getElementById("mcp-current-tool").textContent = "Waiting for a tool call";
      return;
    }
    const branch = Array.from(branches).find(item => item.dataset.category === category);
    if (!branch) return;
    document.getElementById("mcp-current-tool").textContent = tool
      ? `${agent || "Agent"} → ${tool}`
      : "MCP tool call";
    highlightEscalationTool(tool);
    branch.classList.add("active");
    window.setTimeout(() => {
      if (flash === toolCategoryFlash) branch.classList.remove("active");
    }, 900);
  }

  function pulseStageArrow(id) {
    flashElement(document.getElementById(id));
  }

  function updateDecisionOutcome(state) {
    const ticketId = state.running_ticket_id || state.last_ticket_id;
    const ticket = state.tickets.find(item => item.id === ticketId);
    if (!ticket || !["resolved", "escalated"].includes(ticket.status)) return;

    const escalated = ticket.status === "escalated";
    document.getElementById("route-knowledge").classList.toggle("selected", !escalated);
    document.getElementById("route-escalation").classList.toggle("selected", escalated);
    document.getElementById("route-resolution").classList.toggle("selected", !escalated);
    const escalationNote = document.querySelector("#route-escalation .route-result");
    escalationNote.classList.toggle("selected", escalated);
  }

  function appendEvent(event) {
    const row = makeElement("article", `event ${event.type}`);
    let title = "";
    let detail = event.detail || "";
    if (event.type === "agent" && event.action === "ticket started") {
      activeTicketPlaybackId = event.ticket_id;
    }
    if (event.type === "agent") {
      title = `${event.agent} · ${event.action}`;
      highlightNode(event.agent);
      if (event.action === "ticket started") {
        flashElement(document.getElementById("node-customer"));
        pulseToolCategory(null);
        selectedEscalationTool = null;
        highlightEscalationTool(null);
        document.getElementById("route-knowledge").classList.remove("selected", "not-selected");
        document.getElementById("route-escalation").classList.remove("selected", "not-selected");
        document.getElementById("route-resolution").classList.remove("selected", "not-selected");
        document.querySelector("#route-escalation .route-result").classList.remove("selected", "not-selected");
        document.getElementById("kb-match").textContent = "Waiting for search";
        document.getElementById("kb-confidence").textContent =
          `Match score: — · cutoff: ${confidenceThreshold.toFixed(2)}`;
      }
      const arrowId = stageArrows[event.agent];
      if (arrowId) pulseStageArrow(arrowId);
      if (event.agent === "Responder" && event.action === "started") {
        pulseStageArrow("arrow-responder-split");
      }
    } else if (event.type === "tool") {
      highlightNode(event.agent);
      pulseToolCategory(event.category, event.tool, event.agent);
      if (event.tool === "log_event") {
        flashElement(document.getElementById("node-mcp"));
        return;
      }
      if (event.phase === "request") {
        title = `MCP request → ${event.tool}`;
        const parameters = event.arguments || {};
        const summary = parameters.query || parameters.message || parameters.summary;
        detail = `Ticket #${event.ticket_id || "—"}${summary ? ` · ${String(summary).slice(0, 100)}` : ""}`;
        if (event.tool === "search_kb") {
          pulseStageArrow("arrow-responder-knowledge-base");
          flashElement(document.getElementById("node-knowledge-base"));
        }
      } else if (event.phase === "response") {
        title = `MCP response ← ${event.tool}`;
        detail = compactResult(event.result);
        pulseToolCategory(event.category, event.tool, event.agent);
        if (event.tool === "search_kb") {
          const result = event.result || {};
          const confidence = Number(result.confidence);
          const meetsThreshold = confidence >= confidenceThreshold;
          document.getElementById("kb-match").textContent = result.article_id
            ? `${result.article_id} · ${result.title}`
            : "No matching article";
          document.getElementById("kb-confidence").textContent =
            `Match score: ${confidence.toFixed(2)} · cutoff: ${confidenceThreshold.toFixed(2)} · ${meetsThreshold ? "suitable match" : "escalate"}`;
          flashElement(document.getElementById("node-knowledge-base"));
          flashElement(document.getElementById("arrow-knowledge-base-responder"));
        }
      } else {
        title = `MCP error · ${event.tool}`;
      }
      flashElement(document.getElementById("node-mcp"));
    } else if (event.type === "complete") {
      title = `Ticket #${event.ticket_id} processed`;
      pulseToolCategory(null);
      updateDecisionOutcome(latestState);
    } else {
      title = "Demo error";
      errorBanner.style.display = "block";
      errorBanner.textContent = detail;
    }

    row.append(
      makeElement("div", "event-title", title),
      makeElement("div", "event-meta", event.ticket_id ? `Ticket #${event.ticket_id}` : "")
    );
    if (detail) row.append(makeElement("div", "event-detail", detail));
    activityElement.append(row);
    activityElement.scrollTop = activityElement.scrollHeight;
  }

  function updateStats(state) {
    const resolved = state.tickets.filter(ticket => ticket.status === "resolved").length;
    const escalated = state.tickets.filter(ticket => ticket.status === "escalated").length;
    document.getElementById("stat-total").textContent = state.tickets.length;
    document.getElementById("stat-resolved").textContent = resolved;
    document.getElementById("stat-escalated").textContent = escalated;
    document.getElementById("stat-tools").textContent = state.tool_calls;
  }

  function playNextEvent() {
    const event = eventQueue.shift();
    if (!event) {
      playingEvents = false;
      if (latestState && latestState.status !== "running") {
        activeTicketPlaybackId = null;
        renderTickets(latestState.tickets);
        updateStats(latestState);
        updateDecisionOutcome(latestState);
      }
      return;
    }

    playingEvents = true;
    appendEvent(event);
    window.setTimeout(playNextEvent, event.type === "tool" ? 450 : 300);
  }

  function updateState(state) {
    latestState = state;
    if (state.running_ticket_id) activeTicketPlaybackId = state.running_ticket_id;
    if (initialStateLoaded) {
      for (const event of state.events) {
        eventQueue.push(event);
      }
    } else {
      initialStateLoaded = true;
    }
    eventCursor = state.latest_event_id;
    if (!playingEvents) playNextEvent();
    running = state.status === "running" || playingEvents || eventQueue.length > 0;
    renderTickets(state.tickets);
    if (!running) updateStats(state);
    resetButton.hidden = state.status !== "completed" || running;
    statusElement.textContent = running
      ? state.status === "running"
        ? `Processing ticket #${state.running_ticket_id}…`
        : "Playing ticket activity…"
      : state.status === "completed"
        ? "All five tickets have been processed."
        : state.status === "failed"
          ? "The last ticket stopped with an error. You can retry it."
          : state.last_ticket_id
            ? `Ticket #${state.last_ticket_id} finished. Choose another ticket to continue.`
            : "Choose a ticket to begin.";
  }

  async function poll() {
    try {
      const response = await fetch(`/api/state?after=${eventCursor}`, {cache: "no-store"});
      if (!response.ok) throw new Error(`Dashboard request failed (${response.status}).`);
      updateState(await response.json());
    } catch (error) {
      statusElement.textContent = error.message;
    }
  }

  ticketsElement.addEventListener("click", async event => {
    const button = event.target.closest(".ticket-button");
    if (!button || button.disabled) return;
    const ticketId = Number(button.dataset.ticketId);
    errorBanner.style.display = "none";
    try {
      button.disabled = true;
      const response = await fetch("/api/run", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ticket_id: ticketId})
      });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(body.error || `Could not start ticket (${response.status}).`);
      }
      await poll();
    } catch (error) {
      await poll();
      statusElement.textContent = error.message;
    }
  });

  resetButton.addEventListener("click", async () => {
    resetButton.disabled = true;
    errorBanner.style.display = "none";
    try {
      const response = await fetch("/api/reset", {method: "POST"});
      if (!response.ok) {
        const body = await response.json();
        throw new Error(body.error || `Could not reset tickets (${response.status}).`);
      }
      eventQueue.length = 0;
      eventCursor = 0;
      activityElement.replaceChildren();
      activeTicketPlaybackId = null;
      activeNodeId = null;
      selectedEscalationTool = null;
      highlightEscalationTool(null);
      pulseToolCategory(null);
      document.querySelectorAll(".node.active, .flow-arrow.active, .agent-mcp-connection.active")
        .forEach(element => element.classList.remove("active"));
      for (const id of ["route-knowledge", "route-escalation", "route-resolution"]) {
        document.getElementById(id).classList.remove("selected", "not-selected");
      }
      document.querySelector("#route-escalation .route-result")
        .classList.remove("selected", "not-selected");
      document.getElementById("kb-match").textContent = "Waiting for search";
      document.getElementById("kb-confidence").textContent =
        `Match score: — · cutoff: ${confidenceThreshold.toFixed(2)}`;
      await poll();
    } catch (error) {
      errorBanner.style.display = "block";
      errorBanner.textContent = error.message;
      resetButton.disabled = false;
    }
  });

  poll();
  updateMcpConnections();
  window.addEventListener("resize", updateMcpConnections);
  window.setInterval(poll, 350);
</script>
</body>
</html>"""


@app.get("/")
def index():
    return render_template_string(PAGE, confidence_threshold=f"{CONFIDENCE_THRESHOLD:.2f}")


@app.get("/api/state")
def get_state():
    try:
        after = max(0, int(request.args.get("after", "0")))
    except ValueError:
        return jsonify(error="after must be a non-negative integer"), 400
    with _state_lock:
        events = [event for event in _state["events"] if event["id"] > after]
        tool_calls = sum(event["type"] == "tool" and event["phase"] == "request"
                         for event in _state["events"])
        return jsonify(
            status=_state["status"],
            tickets=deepcopy(_state["tickets"]),
            events=deepcopy(events),
            latest_event_id=_state["next_event_id"] - 1,
            tool_calls=tool_calls,
            running_ticket_id=_state["running_ticket_id"],
            last_ticket_id=_state["last_ticket_id"],
            error=_state["error"],
        )


@app.post("/api/run")
def start_run():
    body = request.get_json(silent=True)
    ticket_id = body.get("ticket_id") if isinstance(body, dict) else None
    if isinstance(ticket_id, bool) or not isinstance(ticket_id, int):
        return jsonify(error="ticket_id must be an integer"), 400

    with _state_lock:
        if _state["status"] == "running":
            return jsonify(error="Another ticket is already being processed."), 409
        ticket = next((item for item in _state["tickets"] if item["id"] == ticket_id), None)
        if ticket is None:
            return jsonify(error="Ticket not found."), 404
        if ticket["status"] in ("resolved", "escalated"):
            return jsonify(error="This ticket has already been processed."), 409

        ticket.update(status="processing", category=None, priority=None, handled_by=None)
        _state["status"] = "running"
        _state["running_ticket_id"] = ticket_id
        _state["last_ticket_id"] = None
        _state["error"] = None
        _append_event({
            "type": "agent",
            "agent": "Classifier",
            "ticket_id": ticket_id,
            "action": "ticket started",
            "detail": f"Customer query sent to the classifier for ticket #{ticket_id}.",
        })
        threading.Thread(
            target=_run_demo,
            args=(ticket_id,),
            name=f"ticket-demo-{ticket_id}",
            daemon=True,
        ).start()
    return jsonify(status="running", ticket_id=ticket_id), 202


@app.post("/api/reset")
def reset_demo():
    with _state_lock:
        if _state["status"] != "completed":
            return jsonify(error="All tickets must be processed before resetting."), 409
        tools.init_data(reset=True)
        _state.clear()
        _state.update({
            "status": "idle",
            "tickets": _sample_tickets(),
            "events": [],
            "next_event_id": 1,
            "running_ticket_id": None,
            "last_ticket_id": None,
            "error": None,
        })
    return jsonify(status="idle")


@app.get("/healthz")
def health():
    return jsonify(status="ok")


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    return response


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
