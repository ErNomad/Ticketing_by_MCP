"""MCP and direct in-process hubs for the ticket demo."""

import json
import sys
from contextlib import AsyncExitStack
from pathlib import Path

import tools

SERVER_FILE = str(Path(__file__).with_name("mcp_server.py"))
TOOL_CATEGORIES = {
    "list_new_tickets": "Ticketing",
    "get_ticket": "Ticketing",
    "update_ticket": "Ticketing",
    "send_reply": "Ticketing",
    "get_customer_feedback": "Ticketing",
    "search_kb": "Knowledge Base",
    "escalate_to_security_team": "Escalations",
    "escalate_to_billing_team": "Escalations",
    "escalate_to_it_support": "Escalations",
    "log_event": "Audit",
    "all_tickets": "Ticketing",
    "all_escalations": "Escalations",
}


class Hub:
    def __init__(self, on_event=None):
        self.on_event = on_event
        self.current_ticket_id = None
        self.current_agent = None

    def _emit(self, event):
        if self.on_event is not None:
            self.on_event(event)

    def agent_event(self, agent, ticket_id, action, detail):
        self.current_agent = agent
        self.current_ticket_id = ticket_id
        self._emit({
            "type": "agent",
            "agent": agent,
            "ticket_id": ticket_id,
            "action": action,
            "detail": detail,
        })

    async def call(self, tool, **args):
        if tool != "log_event":  # keep the trace readable
            shown = ", ".join(f"{k}={v[:35]!r}" if isinstance(v, str) else f"{k}={v}"
                              for k, v in args.items())
            print(f"        tool call: {tool}({shown})")
        if "ticket_id" in args:
            self.current_ticket_id = args["ticket_id"]
        event = {
            "type": "tool",
            "tool": tool,
            "category": TOOL_CATEGORIES.get(tool, "Other"),
            "ticket_id": self.current_ticket_id,
            "agent": self.current_agent,
            "arguments": args,
            "phase": "request",
        }
        self._emit(event)
        try:
            result = await self._call(tool, args)
        except Exception as error:
            self._emit({**event, "phase": "error", "detail": str(error)})
            raise
        if tool == "get_ticket" and not result.get("error"):
            self.current_ticket_id = result["id"]
        self._emit({**event, "phase": "response", "result": result})
        return result


class DirectHub(Hub):
    def __init__(self, on_event=None):
        super().__init__(on_event)
        names = ["list_new_tickets", "get_ticket", "update_ticket", "send_reply",
                 "get_customer_feedback", "search_kb", "escalate_to_security_team",
                 "escalate_to_billing_team", "escalate_to_it_support", "log_event",
                 "all_tickets", "all_escalations"]
        self.funcs = {n: getattr(tools, n) for n in names}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def _call(self, tool, args):
        return self.funcs[tool](**args)


class MCPHub(Hub):
    def __init__(self, on_event=None):
        super().__init__(on_event)

    async def __aenter__(self):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            raise SystemExit("The 'mcp' package is missing. Run: pip install mcp "
                             "(or use --direct to skip MCP).")
        self.stack = AsyncExitStack()
        try:
            params = StdioServerParameters(command=sys.executable, args=[SERVER_FILE])
            read, write = await self.stack.enter_async_context(stdio_client(params))
            session = await self.stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.routes = {}
            for tool in (await session.list_tools()).tools:
                self.routes[tool.name] = session
            print(f"Connected to the ticket MCP server, {len(self.routes)} tools available\n")
            return self
        except Exception:
            await self.stack.aclose()
            raise

    async def __aexit__(self, *exc):
        await self.stack.aclose()

    async def _call(self, tool, args):
        session = self.routes.get(tool)
        if session is None:
            raise RuntimeError(f"MCP server does not provide tool {tool!r}")
        result = await session.call_tool(tool, args)
        if result.isError:
            text = result.content[0].text if result.content else "unknown MCP tool error"
            raise RuntimeError(f"{tool} failed: {text}")
        if not result.content:
            raise RuntimeError(f"{tool} returned no MCP content")
        try:
            return json.loads(result.content[0].text)
        except (IndexError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError(f"{tool} returned invalid JSON") from error
