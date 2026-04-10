"""Shared metric computation functions for RAG and Fine-Tune evaluation."""

from eval.lib.kubectl_parser import (
    extract_kubectl_commands,
    detect_dangerous_commands,
    command_similarity,
)


def keyword_recall(answer: str, expected_keywords: list[str]) -> float:
    """Compute fraction of expected keywords found in the answer.

    Case-insensitive matching. Returns 0.0-1.0.
    """
    if not expected_keywords:
        return 1.0
    answer_lower = answer.lower()
    found = sum(1 for kw in expected_keywords if kw.lower() in answer_lower)
    return found / len(expected_keywords)


def command_recall(answer: str, expected_commands: list[str]) -> float:
    """Compute fraction of expected kubectl commands found in the answer.

    Uses fuzzy matching: an expected command is 'found' if any extracted
    command has similarity >= 0.5 with it.
    """
    if not expected_commands:
        return 1.0
    extracted = extract_kubectl_commands(answer)
    if not extracted:
        return 0.0

    found = 0
    for expected in expected_commands:
        for actual in extracted:
            if command_similarity(expected, actual) >= 0.5:
                found += 1
                break
    return found / len(expected_commands)


def hallucination_score(answer: str) -> float:
    """Score from 0.0-1.0 where 1.0 means no hallucinated/dangerous commands.

    Checks for dangerous kubectl patterns and nonsensical suggestions.
    """
    dangerous = detect_dangerous_commands(answer)
    extracted = extract_kubectl_commands(answer)
    total = max(len(extracted), 1)
    return 1.0 - (len(dangerous) / total)


def structure_score(answer: str) -> float:
    """Score from 0.0-1.0 measuring diagnostic structure quality.

    Checks for presence of key diagnostic sections.
    """
    structure_elements = [
        ["root cause", "cause", "reason", "why"],
        ["diagnosis", "diagnostic", "investigation", "analysis"],
        ["resolution", "solution", "fix", "resolve"],
        ["kubectl", "command"],
        ["step", "1.", "2.", "first", "then"],
    ]
    answer_lower = answer.lower()
    found = 0
    for synonyms in structure_elements:
        if any(s in answer_lower for s in synonyms):
            found += 1
    return found / len(structure_elements)


def compute_all_metrics(answer: str, test_case: dict) -> dict:
    """Compute all metrics for a single test case."""
    return {
        "retrieval_keyword_recall": keyword_recall(
            answer, test_case.get("expected_retrieval_keywords", [])
        ),
        "answer_keyword_coverage": keyword_recall(
            answer, test_case.get("expected_answer_keywords", [])
        ),
        "command_recall": command_recall(
            answer, test_case.get("expected_kubectl_commands", [])
        ),
        "hallucination_score": hallucination_score(answer),
        "structure_score": structure_score(answer),
    }


def compute_diagnose_metrics(diagnosis: str, test_case: dict) -> dict:
    """Compute metrics for diagnose endpoint test cases."""
    return {
        "diagnosis_keyword_coverage": keyword_recall(
            diagnosis, test_case.get("expected_diagnosis_keywords", [])
        ),
        "command_recall": command_recall(
            diagnosis, test_case.get("expected_kubectl_commands", [])
        ),
        "hallucination_score": hallucination_score(diagnosis),
        "structure_score": structure_score(diagnosis),
    }


def aggregate_metrics(results: list[dict], metric_key: str = "rag") -> dict:
    """Aggregate metrics across multiple test cases."""
    if not results:
        return {}

    all_metrics = [r[metric_key] for r in results if metric_key in r]
    if not all_metrics:
        return {}

    keys = all_metrics[0].keys()
    aggregated = {}
    for key in keys:
        values = [m[key] for m in all_metrics if key in m]
        if values:
            aggregated[key] = {
                "mean": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
                "count": len(values),
            }
    return aggregated


def aggregate_by_category(results: list[dict], metric_key: str = "rag") -> dict:
    """Aggregate metrics grouped by incident category."""
    categories = {}
    for r in results:
        cat = r.get("category", "unknown")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r)

    return {cat: aggregate_metrics(items, metric_key) for cat, items in categories.items()}
