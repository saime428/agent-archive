from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent.config import AgentConfig
from agent.core.actions import InternalAction
from agent.core.tool_catalog import ToolDefinition, builtin_tool_catalog

DecisionStatus = Literal["allow", "approval_required", "deny"]


@dataclass(frozen=True)
class PolicyDecision:
    status: DecisionStatus
    reason: str


def _builtin_names(risk: str) -> set[str]:
    return {
        definition.name
        for definition in builtin_tool_catalog().definitions
        if definition.risk == risk
    }


LOW_RISK_ACTIONS = _builtin_names("low-risk") | {"done"}
CONFIRMATION_REQUIRED_ACTIONS = _builtin_names("confirmation-required")


def _mcp_approval_reason(definition: ToolDefinition) -> str:
    return (
        f"MCP tool {definition.name!r} from server {definition.server_id!r} "
        f"(remote tool {definition.remote_name!r}) executes through a server process "
        "with the user's OS permissions; approval is required for every call."
    )


def classify_action(
    action: InternalAction,
    config: AgentConfig,
    definition: ToolDefinition | None = None,
) -> PolicyDecision:
    action_name = action.action.name
    resolved = definition or builtin_tool_catalog().resolve(action_name)
    if resolved is None or resolved.name != action_name:
        return PolicyDecision("deny", "Action is not supported by policy.")

    if resolved.source == "mcp":
        reason = _mcp_approval_reason(resolved)
        if config.sandbox == "read-only":
            return PolicyDecision("deny", f"{reason} The read-only sandbox denies this call.")
        if config.approval == "never":
            return PolicyDecision("deny", f"{reason} Approval is disabled, so this call is denied.")
        return PolicyDecision("approval_required", reason)

    approval_reason = "Action requires approval before execution."
    if action_name == "run_command":
        approval_reason = (
            "Run commands execute local processes with the agent's OS permissions; "
            "workspace path checks do not fully contain file, network, or subprocess access. Approval is required."
        )
    if action_name == "done":
        return PolicyDecision("allow", "Done actions are always allowed.")
    if action_name == "ask_user":
        return PolicyDecision("allow", "Ask-user terminal actions are always allowed.")
    if action_name == "web_search" and not config.web_search_enabled:
        return PolicyDecision("deny", "Web search is disabled. Enable it in Settings before searching the internet.")
    if config.sandbox == "read-only" and resolved.risk == "confirmation-required":
        return PolicyDecision("deny", "Action is blocked by read-only sandbox.")

    if config.approval == "always":
        return PolicyDecision("approval_required", approval_reason)

    if resolved.risk == "low-risk":
        return PolicyDecision("allow", "Low-risk action is allowed.")

    if resolved.risk == "confirmation-required":
        if config.approval == "never":
            return PolicyDecision(
                "deny",
                "Approval is disabled; confirmation-required actions are denied.",
            )
        return PolicyDecision("approval_required", approval_reason)

    return PolicyDecision("deny", "Action is not supported by policy.")
