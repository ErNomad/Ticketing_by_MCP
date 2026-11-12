"""
Three rule-based agents and a small router. Agents only act through tools (via the hub).

Classifier : reads the ticket, checks the knowledge base, and CHOOSES a tool:
             send_reply (answer from KB) or one of the escalate_to_* tools.
Responder  : sends the KB answer, then reads the customer's feedback.
Escalation : raises the ticket with the team's escalation tool.
"""

CONFIDENCE_THRESHOLD = 0.6

# First match wins, so the order matters (security before billing, etc.)
CATEGORY_KEYWORDS = {
    "security": ["hacked", "unauthorized", "suspicious", "did not make", "breach"],
    "billing": ["charged", "refund", "payment", "invoice", "billing", "subscription"],
    "access": ["password", "login", "locked out"],
    "network": ["vpn", "wifi", "network", "connect"],
}
ESCALATION_TOOL = {
    "security": "escalate_to_security_team",
    "billing": "escalate_to_billing_team",
}
DEFAULT_ESCALATION_TOOL = "escalate_to_it_support"
NEGATIVE_WORDS = ["still", "doesn't", "does not", "didn't", "did not", "not work", "no luck"]


class Agent:
    name = "Agent"

    def __init__(self, hub):
        self.hub = hub

    async def log(self, ticket_id, action, detail=""):
        print(f"  [{self.name}] {action}: {detail}")
        self.hub.agent_event(self.name, ticket_id, action, detail)
        await self.hub.call("log_event", agent=self.name, ticket_id=ticket_id,
                            action=action, detail=detail)


class ClassifierAgent(Agent):
    name = "Classifier"

    async def handle(self, ticket_id):
        self.hub.agent_event(self.name, ticket_id, "started", "")
        ticket = await self.hub.call("get_ticket", ticket_id=ticket_id)
        text = ticket["text"].lower()

        category = next((cat for cat, words in CATEGORY_KEYWORDS.items()
                         if any(w in text for w in words)), "general")
        if category == "security":
            priority = "critical"
        elif "refund" in text or "charged" in text:
            priority = "high"
        else:
            priority = "normal"

        escalation_tool = ESCALATION_TOOL.get(category, DEFAULT_ESCALATION_TOOL)

        await self.hub.call("update_ticket", ticket_id=ticket_id, status="classified",
                            category=category, priority=priority, handled_by=self.name)
        await self.log(ticket_id, "classified", f"category={category}, priority={priority}")
        return {"category": category, "priority": priority,
                "article": None, "escalation_tool": escalation_tool}


class ResponderAgent(Agent):
    name = "Responder"

    async def handle(self, ticket_id, decision):
        """Returns True if the customer confirms the fix, False if it did not work."""
        self.hub.agent_event(self.name, ticket_id, "started", "")
        ticket = await self.hub.call("get_ticket", ticket_id=ticket_id)
        article = await self.hub.call("search_kb", query=ticket["text"])
        decision["article"] = article
        if article["confidence"] < CONFIDENCE_THRESHOLD:
            await self.log(
                ticket_id,
                "no confident knowledge base match",
                f"best confidence {article['confidence']:.2f}; forwarding to escalation",
            )
            return False

        await self.log(
            ticket_id,
            "found knowledge base match",
            f"{article['article_id']} {article['title']}, confidence {article['confidence']:.2f}",
        )
        article = decision["article"]
        steps = "\n".join(f"  {i}. {s}" for i, s in enumerate(article["steps"], 1))
        message = (f"Hi {ticket['customer']}, this should help ({article['title']}):\n"
                   f"{steps}\nLet us know if it works.")
        await self.hub.call("send_reply", ticket_id=ticket_id, message=message)
        await self.hub.call("update_ticket", ticket_id=ticket_id, status="answered",
                            handled_by=self.name)
        await self.log(ticket_id, "replied from knowledge base",
                       f"{article['article_id']} {article['title']}")

        feedback = (await self.hub.call("get_customer_feedback", ticket_id=ticket_id))["feedback"]
        if any(w in feedback.lower() for w in NEGATIVE_WORDS):
            await self.log(ticket_id, "customer says it did not work", f'"{feedback}"')
            return False
        await self.hub.call("update_ticket", ticket_id=ticket_id, status="resolved")
        await self.log(ticket_id, "customer confirmed the fix", f'"{feedback}"')
        return True


class EscalationAgent(Agent):
    name = "Escalation"

    async def handle(self, ticket_id, decision, reason):
        self.hub.agent_event(self.name, ticket_id, "started", "")
        ticket = await self.hub.call("get_ticket", ticket_id=ticket_id)
        summary = (f"[{decision['priority'].upper()}] {decision['category']}: {ticket['text']} "
                   f"| Why escalated: {reason}")
        result = await self.hub.call(decision["escalation_tool"], ticket_id=ticket_id,
                                     summary=summary)
        await self.hub.call("update_ticket", ticket_id=ticket_id, status="escalated",
                            handled_by=self.name)
        await self.log(ticket_id, f"escalated to {result['team']}",
                       f"ref {result['reference']} via {decision['escalation_tool']}; {reason}")


async def triage(hub, ticket_id):
    """Route one ticket through the classifier, responder, and when needed escalation."""
    classifier, responder, escalation = ClassifierAgent(hub), ResponderAgent(hub), EscalationAgent(hub)

    decision = await classifier.handle(ticket_id)
    if await responder.handle(ticket_id, decision):
        return
    if decision["article"]["confidence"] >= CONFIDENCE_THRESHOLD:
        reason = "customer reported that the knowledge base solution did not work"
    else:
        reason = "no confident knowledge base solution"
    await escalation.handle(ticket_id, decision, reason)
