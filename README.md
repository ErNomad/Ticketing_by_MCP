# Ticket Agent MCP Demo

An interactive dashboard demonstrating a classifier, responder, and escalation agent using real
Model Context Protocol (MCP) tool calls against five hardcoded sample support tickets.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python dashboard.py
```

Open <http://127.0.0.1:5000> and click **Start ticket** on one ticket at a time. Follow its
classifier, responder, knowledge-base, and escalation steps in the paced animated flow and activity log.
The MCP category block highlights the ticketing, knowledge-base, escalation, or audit tool in use.
The knowledge-base block shows its rule-based keyword match score and the escalation cutoff; the
score is a demo heuristic, not a probability.
On desktop, tickets, the agent decision flow, and the shared MCP server appear left to right.
The Classifier connects to the shared MCP server; the responder's MCP use is shown through the
knowledge-base tool path. At the end of a ticket, only the final outcome is green: Knowledge Base
when its answer resolves the ticket, or Escalation when the ticket is routed to a team.
Only the final outcome is highlighted after playback finishes; the alternative stays neutral.
Incompatible escalation-team tools are shown in red.
After all five tickets have been processed, use **Reset all** to clear the activity and restart
your demo. Each browser gets its own signed session and isolated in-memory tickets, MCP activity,
replies, and escalations. Sessions expire after two hours of inactivity; the in-memory data is
also cleared when the service restarts. The single service instance supports up to 500 sessions;
when full, new sessions receive a retry-later response rather than replacing an active demo. No
database is required.

To run the command-line version, use `python demo.py` for MCP or `python demo.py --direct` to call
the same tools in-process.

## Deploy on Render

Create a **Web Service** using the Python runtime and configure:

- **Build command:** `pip install -r requirements.txt`
- **Start command:** `gunicorn dashboard:app --bind 0.0.0.0:$PORT --workers 1 --threads 4`
- **Health check path:** `/healthz`

Render supplies `PORT`. Keep one Gunicorn worker and one service instance: each worker keeps its
own in-memory browser sessions and MCP server, so state is not shared across workers or instances.

The dashboard is public and has no authentication. It uses sample data only; it is not connected
to a real ticketing system and is not suitable for real customer or confidential support data.
