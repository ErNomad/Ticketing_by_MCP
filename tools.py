"""In-memory demo data and business logic exposed through MCP tools."""

from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import RLock
from time import monotonic

# ---------------------------------------------------------------- knowledge base

KB_ARTICLES = [
    {"id": "KB-101", "title": "Reset your password",
     "keywords": ["password", "reset", "forgot", "locked out"],
     "steps": ["Open the login page and click 'Forgot password'.",
               "Enter your account email and request a reset link.",
               "Click the link in the email (valid for 30 minutes) and choose a new password."]},
    {"id": "KB-102", "title": "Download invoices and receipts",
     "keywords": ["invoice", "download", "receipt", "statement"],
     "steps": ["Sign in and open Account > Billing.",
               "Pick the month under 'Invoices'.",
               "Click 'Download PDF'."]},
    {"id": "KB-103", "title": "Troubleshoot VPN connection problems",
     "keywords": ["vpn", "connect", "connection", "timeout"],
     "steps": ["Check that your internet works without the VPN.",
               "Quit and restart the VPN client, then sign in again.",
               "Switch the protocol to 'TCP' in the VPN settings and reconnect."]},
    {"id": "KB-104", "title": "Update your payment method",
     "keywords": ["payment", "card", "update", "billing"],
     "steps": ["Open Account > Billing > Payment method.",
               "Add the new card and set it as default."]},
]

# ---------------------------------------------------------------- demo tickets
# (customer, ticket text, what the customer answers after receiving a KB reply)
SEED_TICKETS = [
    ("Anna", "I forgot my password and now I am locked out of my account. How can I reset it?",
     "Thanks, that worked and I'm back in!"),
    ("Erik", "Where can I download last month's invoice? I need a receipt for my accounting.",
     "Got it, thank you!"),
    ("Maria", "My VPN will not connect from home since this morning. It says connection timed out.",
     "I followed every step but it still doesn't connect. Please help."),
    ("Lars", "I was charged twice for my subscription this month. Please refund the duplicate payment.",
     ""),
    ("Sofia", "I got alerts about logins from another country that I did not make. I think someone hacked my account.",
     ""),
]

_lock = RLock()
_sessions = {}
_session_last_used = {}
_SESSION_TTL_SECONDS = 2 * 60 * 60
_MAX_SESSIONS = 500


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_session_data():
    return {
        "tickets": [
            {
                "id": ticket_id,
                "customer": customer,
                "text": text,
                "customer_feedback": feedback,
                "category": None,
                "priority": None,
                "status": "new",
                "handled_by": None,
            }
            for ticket_id, (customer, text, feedback) in enumerate(SEED_TICKETS, 1)
        ],
        "replies": [],
        "escalations": [],
        "events": [],
    }


@contextmanager
def _session_data(session_id):
    if not isinstance(session_id, str) or not session_id or len(session_id) > 128:
        raise ValueError("A valid demo session ID is required.")
    with _lock:
        now = monotonic()
        expired = [
            key for key, last_used in _session_last_used.items()
            if now - last_used > _SESSION_TTL_SECONDS
        ]
        for key in expired:
            _sessions.pop(key, None)
            _session_last_used.pop(key, None)
        if session_id not in _sessions:
            if len(_sessions) >= _MAX_SESSIONS:
                raise RuntimeError("The demo has reached its session limit.")
            _sessions[session_id] = _new_session_data()
        _session_last_used[session_id] = now
        yield _sessions[session_id]


def init_data(reset=False, session_id="default"):
    """Initialize or reset one demo's in-memory data."""
    if not isinstance(session_id, str) or not session_id or len(session_id) > 128:
        raise ValueError("A valid demo session ID is required.")
    with _lock:
        if session_id not in _sessions and len(_sessions) >= _MAX_SESSIONS:
            raise RuntimeError("The demo has reached its session limit.")
        if reset or session_id not in _sessions:
            _sessions[session_id] = _new_session_data()
        _session_last_used[session_id] = monotonic()

# ---------------------------------------------------------------- tickets tools

def list_new_tickets(session_id="default") -> list:
    with _session_data(session_id) as data:
        return [
            {key: ticket[key] for key in ("id", "customer", "text")}
            for ticket in data["tickets"] if ticket["status"] == "new"
        ]


def get_ticket(ticket_id: int, session_id="default") -> dict:
    with _session_data(session_id) as data:
        for ticket in data["tickets"]:
            if ticket["id"] == ticket_id:
                return {key: value for key, value in ticket.items() if key != "customer_feedback"}
        return {"error": f"ticket {ticket_id} not found"}


def update_ticket(ticket_id: int, status: str = "", category: str = "",
                  priority: str = "", handled_by: str = "",
                  session_id="default") -> dict:
    with _session_data(session_id) as data:
        for ticket in data["tickets"]:
            if ticket["id"] == ticket_id:
                for key, value in (
                    ("status", status),
                    ("category", category),
                    ("priority", priority),
                    ("handled_by", handled_by),
                ):
                    if value:
                        ticket[key] = value
                return {key: value for key, value in ticket.items()
                        if key != "customer_feedback"}
        return {"error": f"ticket {ticket_id} not found"}


def send_reply(ticket_id: int, message: str, session_id="default") -> dict:
    with _session_data(session_id) as data:
        if not any(ticket["id"] == ticket_id for ticket in data["tickets"]):
            return {"error": f"ticket {ticket_id} not found"}
        reply_id = len(data["replies"]) + 1
        data["replies"].append(
            {"id": reply_id, "ticket_id": ticket_id, "message": message, "created": _now()}
        )
        return {"ok": True, "reply_id": reply_id}


def get_customer_feedback(ticket_id: int, session_id="default") -> dict:
    """Simulates the customer's answer to our reply (in real life this arrives later)."""
    with _session_data(session_id) as data:
        for ticket in data["tickets"]:
            if ticket["id"] == ticket_id:
                return {"feedback": ticket["customer_feedback"]}
        return {"error": f"ticket {ticket_id} not found", "feedback": ""}

# ---------------------------------------------------------------- knowledge base tool

def search_kb(query: str, session_id="default") -> dict:
    """Keyword match. Each matching keyword adds 0.35 confidence (capped at 1.0)."""
    with _session_data(session_id):
        pass
    text = query.lower()
    best = {"article_id": None, "title": None, "steps": [], "confidence": 0.0}
    for article in KB_ARTICLES:
        hits = sum(1 for k in article["keywords"] if k in text)
        confidence = round(min(1.0, hits * 0.35), 2)
        if confidence > best["confidence"]:
            best = {"article_id": article["id"], "title": article["title"],
                    "steps": article["steps"], "confidence": confidence}
    return best

# ---------------------------------------------------------------- escalation tools

def _escalate(team: str, prefix: str, ticket_id: int, summary: str, session_id) -> dict:
    with _session_data(session_id) as data:
        if not any(ticket["id"] == ticket_id for ticket in data["tickets"]):
            return {"error": f"ticket {ticket_id} not found"}
        row_id = len(data["escalations"]) + 1
        reference = f"{prefix}-{row_id:04d}"
        data["escalations"].append(
            {"reference": reference, "team": team, "ticket_id": ticket_id,
             "summary": summary, "created": _now()}
        )
        return {"reference": reference, "team": team}


def escalate_to_security_team(ticket_id: int, summary: str, session_id="default") -> dict:
    return _escalate("Security Team", "SEC", ticket_id, summary, session_id)


def escalate_to_billing_team(ticket_id: int, summary: str, session_id="default") -> dict:
    return _escalate("Billing Team", "BILL", ticket_id, summary, session_id)


def escalate_to_it_support(ticket_id: int, summary: str, session_id="default") -> dict:
    return _escalate("IT Support", "IT", ticket_id, summary, session_id)

# ---------------------------------------------------------------- audit tool

def log_event(agent: str, ticket_id: int, action: str, detail: str = "",
              session_id="default") -> dict:
    with _session_data(session_id) as data:
        data["events"].append(
            {"ts": _now(), "agent": agent, "ticket_id": ticket_id,
             "action": action, "detail": detail}
        )
        return {"ok": True}

# ---------------------------------------------------------------- read helpers

def all_tickets(session_id="default"):
    with _session_data(session_id) as data:
        return [
            {key: value for key, value in ticket.items() if key != "customer_feedback"}
            for ticket in data["tickets"]
        ]


def all_events(session_id="default"):
    with _session_data(session_id) as data:
        return deepcopy(data["events"])


def all_escalations(session_id="default"):
    with _session_data(session_id) as data:
        return deepcopy(data["escalations"])
