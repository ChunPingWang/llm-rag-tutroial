"""Extract and analyze kubectl commands from text."""

import re

# Dangerous command patterns that indicate hallucination or unsafe suggestions
DANGEROUS_PATTERNS = [
    r"kubectl\s+delete\s+namespace\s+kube-system",
    r"kubectl\s+delete\s+node",
    r"kubectl\s+delete\s+--all\s+--all-namespaces",
    r"rm\s+-rf\s+/",
    r"kubectl\s+drain\s+.*--force\s+--delete-emptydir-data\s+--ignore-daemonsets",
    r"kubectl\s+delete\s+clusterrole",
    r"kubectl\s+delete\s+clusterrolebinding",
]

# Regex to extract kubectl commands from text
KUBECTL_CMD_PATTERN = re.compile(
    r"kubectl\s+(?:get|describe|logs|top|exec|apply|delete|edit|rollout|scale|cordon|uncordon|drain|run|create|patch|label|annotate|port-forward|cp|auth|api-resources|config|explain|events|wait)"
    r"(?:\s+[^\n`\"]{1,200})?",
    re.IGNORECASE,
)

# Also capture kubeadm commands
KUBEADM_CMD_PATTERN = re.compile(
    r"kubeadm\s+(?:certs|token|init|join|reset|upgrade|config)"
    r"(?:\s+[^\n`\"]{1,200})?",
    re.IGNORECASE,
)


def extract_kubectl_commands(text: str) -> list[str]:
    """Extract kubectl and kubeadm commands from text."""
    commands = []
    for match in KUBECTL_CMD_PATTERN.finditer(text):
        cmd = match.group(0).strip().rstrip(".")
        commands.append(cmd)
    for match in KUBEADM_CMD_PATTERN.finditer(text):
        cmd = match.group(0).strip().rstrip(".")
        commands.append(cmd)
    return commands


def extract_command_verbs(text: str) -> list[str]:
    """Extract just the kubectl subcommands (get, describe, logs, etc.)."""
    verbs = set()
    pattern = re.compile(r"kubectl\s+(\w+)", re.IGNORECASE)
    for match in pattern.finditer(text):
        verbs.add(match.group(1).lower())
    pattern2 = re.compile(r"kubeadm\s+(\w+)", re.IGNORECASE)
    for match in pattern2.finditer(text):
        verbs.add(f"kubeadm {match.group(1).lower()}")
    return list(verbs)


def detect_dangerous_commands(text: str) -> list[str]:
    """Detect dangerous or destructive commands in text."""
    dangerous = []
    for pattern in DANGEROUS_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        dangerous.extend(matches)
    return dangerous


def command_similarity(cmd1: str, cmd2: str) -> float:
    """Compute similarity between two kubectl commands based on verb+resource overlap."""
    words1 = set(cmd1.lower().split())
    words2 = set(cmd2.lower().split())
    if not words1 or not words2:
        return 0.0
    intersection = words1 & words2
    return len(intersection) / max(len(words1), len(words2))
