"""
Runs the 5 demo tickets through the agents.

    python demo.py             # agents talk to the tools over MCP
    python demo.py --direct    # same agents, tools called in-process (no mcp package needed)

The dashboard also runs this workflow when its demo button is clicked.
"""

import asyncio
import sys

import tools
from agents import triage
from client import DirectHub, MCPHub

PAUSE_SECONDS = 1.0  # so the dashboard visibly updates ticket by ticket


async def main(use_mcp):
    tools.init_data(reset=True)
    async with (MCPHub() if use_mcp else DirectHub()) as hub:
        for ticket in await hub.call("list_new_tickets"):
            print(f"\n=== Ticket #{ticket['id']} from {ticket['customer']}: {ticket['text']}")
            await triage(hub, ticket["id"])
            await asyncio.sleep(PAUSE_SECONDS)

        tickets = await hub.call("all_tickets")
        escalations = await hub.call("all_escalations")

    print("\n" + "=" * 78)
    print(f"{'#':<3}{'Customer':<10}{'Category':<10}{'Priority':<10}{'Final status':<13}Last handled by")
    for t in tickets:
        print(f"{t['id']:<3}{t['customer']:<10}{t['category']:<10}{t['priority']:<10}"
              f"{t['status']:<13}{t['handled_by']}")
    print("\nEscalations raised:")
    for e in escalations:
        print(f"  {e['reference']:<10}{e['team']:<15}ticket #{e['ticket_id']}")


if __name__ == "__main__":
    asyncio.run(main(use_mcp="--direct" not in sys.argv))
