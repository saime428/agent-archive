from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent.config import AgentConfig
from agent.core.actions import InternalAction

DecisionStatus = Literal["allow", "approval_required", "deny"]

LOW_RISK_ACTIONS = {
    "done",
    "list_dir",
    "read_file",
    "read_pdf",
    "search_files",
    "git_status",
    "git_diff",
}
CONFIRMATION_REQUIRED_ACTIONS = {
    "write_file",
    "apply_patch",
    "run_command",
}


@dataclass(frozen=True)
class PolicyDecision:
    status: DecisionStatus
    reason: str


def classify_action(action: InternalAction, config: AgentConfig) -> PolicyDecision:
    action_name = action.action.name
    if action_name == "done":
        return PolicyDecision("allow", "Done actions are always allowed.")
    if action_name == "ask_user":
        return PolicyDecision("allow", "Ask-user terminal actions are always allowed.")

    if config.approval == "always":
        return PolicyDecision("approval_required", "Action requires approval before execution.")

    if action_name in LOW_RISK_ACTIONS:
        return PolicyDecision("allow", "Low-risk action is allowed.")

    if action_name in CONFIRMATION_REQUIRED_ACTIONS:
        return PolicyDecision("approval_required", "Action requires approval before execution.")

    return PolicyDecision("deny", "Action is not supported by policy.")
