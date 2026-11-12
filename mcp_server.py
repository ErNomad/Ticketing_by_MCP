"""Single-process MCP server for the ticket demo's shared in-memory state."""

import json

from mcp.server.fastmcp import FastMCP

import tools

mcp = FastMCP("ticket-triage-demo")


@mcp.tool()
def list_new_tickets() -> str:
    """List tickets that have not been handled yet."""
    return json.dumps(tools.list_new_tickets())


@mcp.tool()
def get_ticket(ticket_id: int) -> str:
    """Fetch one ticket: customer, text, category, priority, status."""
    return json.dumps(tools.get_ticket(ticket_id))


@mcp.tool()
def update_ticket(ticket_id: int, status: str = "", category: str = "",
                  priority: str = "", handled_by: str = "") -> str:
    """Update ticket fields. Empty values are left unchanged."""
    return json.dumps(tools.update_ticket(ticket_id, status, category, priority, handled_by))


@mcp.tool()
def send_reply(ticket_id: int, message: str) -> str:
    """Send a reply to the customer using the knowledge base."""
    return json.dumps(tools.send_reply(ticket_id, message))


@mcp.tool()
def get_customer_feedback(ticket_id: int) -> str:
    """Get the simulated customer's response to the last reply."""
    return json.dumps(tools.get_customer_feedback(ticket_id))


@mcp.tool()
def search_kb(query: str) -> str:
    """Search the knowledge base and return a confidence score from 0 to 1."""
    return json.dumps(tools.search_kb(query))


@mcp.tool()
def escalate_to_security_team(ticket_id: int, summary: str) -> str:
    """Escalate a ticket to the Security Team."""
    return json.dumps(tools.escalate_to_security_team(ticket_id, summary))


@mcp.tool()
def escalate_to_billing_team(ticket_id: int, summary: str) -> str:
    """Escalate a ticket to the Billing Team."""
    return json.dumps(tools.escalate_to_billing_team(ticket_id, summary))


@mcp.tool()
def escalate_to_it_support(ticket_id: int, summary: str) -> str:
    """Escalate a ticket to IT Support."""
    return json.dumps(tools.escalate_to_it_support(ticket_id, summary))


@mcp.tool()
def log_event(agent: str, ticket_id: int, action: str, detail: str = "") -> str:
    """Record an agent action in the demo's in-memory activity log."""
    return json.dumps(tools.log_event(agent, ticket_id, action, detail))


@mcp.tool()
def all_tickets() -> str:
    """List all demo tickets and their current status."""
    return json.dumps(tools.all_tickets())


@mcp.tool()
def all_escalations() -> str:
    """List escalations raised during this demo run."""
    return json.dumps(tools.all_escalations())


if __name__ == "__main__":
    tools.init_data(reset=True)
    mcp.run()
