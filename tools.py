"""In-memory demo data and business logic exposed through MCP tools."""

from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock

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
_tickets = []
_replies = []
_escalations = []
_events = []


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_data(reset=False):
    """Load the sample tickets; reset all demo activity when requested."""
    global _tickets, _replies, _escalations, _events
    with _lock:
        if reset or not _tickets:
            _tickets = [
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
            ]
            _replies = []
            _escalations = []
            _events = []


init_data()

# ---------------------------------------------------------------- tickets tools

def list_new_tickets() -> list:
    with _lock:
        return [
            {key: ticket[key] for key in ("id", "customer", "text")}
            for ticket in _tickets if ticket["status"] == "new"
        ]


def get_ticket(ticket_id: int) -> dict:
    with _lock:
        for ticket in _tickets:
            if ticket["id"] == ticket_id:
                return {key: value for key, value in ticket.items() if key != "customer_feedback"}
        return {"error": f"ticket {ticket_id} not found"}


def update_ticket(ticket_id: int, status: str = "", category: str = "",
                  priority: str = "", handled_by: str = "") -> dict:
    with _lock:
        for ticket in _tickets:
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


def send_reply(ticket_id: int, message: str) -> dict:
    with _lock:
        if not any(ticket["id"] == ticket_id for ticket in _tickets):
            return {"error": f"ticket {ticket_id} not found"}
        reply_id = len(_replies) + 1
        _replies.append(
            {"id": reply_id, "ticket_id": ticket_id, "message": message, "created": _now()}
        )
        return {"ok": True, "reply_id": reply_id}


def get_customer_feedback(ticket_id: int) -> dict:
    """Simulates the customer's answer to our reply (in real life this arrives later)."""
    with _lock:
        for ticket in _tickets:
            if ticket["id"] == ticket_id:
                return {"feedback": ticket["customer_feedback"]}
        return {"error": f"ticket {ticket_id} not found", "feedback": ""}

# ---------------------------------------------------------------- knowledge base tool

def search_kb(query: str) -> dict:
    """Keyword match. Each matching keyword adds 0.35 confidence (capped at 1.0)."""
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

def _escalate(team: str, prefix: str, ticket_id: int, summary: str) -> dict:
    with _lock:
        if not any(ticket["id"] == ticket_id for ticket in _tickets):
            return {"error": f"ticket {ticket_id} not found"}
        row_id = len(_escalations) + 1
        reference = f"{prefix}-{row_id:04d}"
        _escalations.append(
            {"reference": reference, "team": team, "ticket_id": ticket_id,
             "summary": summary, "created": _now()}
        )
        return {"reference": reference, "team": team}


def escalate_to_security_team(ticket_id: int, summary: str) -> dict:
    return _escalate("Security Team", "SEC", ticket_id, summary)


def escalate_to_billing_team(ticket_id: int, summary: str) -> dict:
    return _escalate("Billing Team", "BILL", ticket_id, summary)


def escalate_to_it_support(ticket_id: int, summary: str) -> dict:
    return _escalate("IT Support", "IT", ticket_id, summary)

# ---------------------------------------------------------------- audit tool

def log_event(agent: str, ticket_id: int, action: str, detail: str = "") -> dict:
    with _lock:
        _events.append(
            {"ts": _now(), "agent": agent, "ticket_id": ticket_id,
             "action": action, "detail": detail}
        )
        return {"ok": True}

# ---------------------------------------------------------------- read helpers

def all_tickets():
    with _lock:
        return [
            {key: value for key, value in ticket.items() if key != "customer_feedback"}
            for ticket in _tickets
        ]


def all_events():
    with _lock:
        return deepcopy(_events)


def all_escalations():
    with _lock:
        return deepcopy(_escalations)
