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
    "read_docx",
    "read_xlsx",
    "read_pptx",
    "search_files",
    "web_search",
    "git_status",
    "git_diff",
}
CONFIRMATION_REQUIRED_ACTIONS = {
    "write_file",
    "apply_patch",
    "run_command",
    "write_markdown_report",
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
    if action_name == "web_search" and not config.web_search_enabled:
        return PolicyDecision("deny", "Web search is disabled. Enable it in Settings before searching the internet.")
    if config.sandbox == "read-only" and action_name in CONFIRMATION_REQUIRED_ACTIONS:
        return PolicyDecision("deny", "Action is blocked by read-only sandbox.")

    if config.approval == "always":
        return PolicyDecision("approval_required", "Action requires approval before execution.")

    if action_name in LOW_RISK_ACTIONS:
        return PolicyDecision("allow", "Low-risk action is allowed.")

    if action_name in CONFIRMATION_REQUIRED_ACTIONS:
        if config.approval == "never":
            return PolicyDecision(
                "deny",
                "Approval is disabled; confirmation-required actions are denied.",
            )
        return PolicyDecision("approval_required", "Action requires approval before execution.")

    return PolicyDecision("deny", "Action is not supported by policy.")
