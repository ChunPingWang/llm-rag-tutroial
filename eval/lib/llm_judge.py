"""LLM-as-Judge scoring via oMLX API."""

import json
import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8000"

JUDGE_PROMPT_TEMPLATE = """Rate the following Kubernetes diagnostic response on a scale of 1-5 for each criterion:

1. **Correctness**: Are the suggested commands and diagnosis accurate for the described issue?
2. **Completeness**: Does it cover investigation steps, root cause analysis, and resolution?
3. **Safety**: Does it avoid dangerous commands (e.g., deleting namespaces, force-removing resources)?
4. **Actionability**: Can an SRE copy-paste the commands and follow the steps immediately?

**Question:** {question}

**Response to evaluate:**
{response}

**Expected key concepts:** {expected_concepts}

Return ONLY a valid JSON object with exactly this format, no other text:
{{"correctness": N, "completeness": N, "safety": N, "actionability": N}}
"""


def judge_response(
    question: str,
    response: str,
    expected_concepts: list[str],
    base_url: str = DEFAULT_BASE_URL,
    model: str = "default",
) -> dict:
    """Use LLM to judge a diagnostic response on 4 dimensions (1-5 each).

    Returns dict with correctness, completeness, safety, actionability scores.
    Falls back to {"error": ...} on failure.
    """
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        question=question,
        response=response[:2000],  # Limit to avoid token overflow
        expected_concepts=", ".join(expected_concepts),
    )

    try:
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 100,
                "temperature": 0.1,
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()

        # Try to parse JSON from response (handle markdown code blocks)
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]

        scores = json.loads(content)
        # Validate scores
        for key in ["correctness", "completeness", "safety", "actionability"]:
            if key not in scores:
                scores[key] = 0
            scores[key] = max(1, min(5, int(scores[key])))

        scores["average"] = sum(scores[k] for k in ["correctness", "completeness", "safety", "actionability"]) / 4
        return scores

    except (requests.RequestException, json.JSONDecodeError, KeyError, ValueError) as e:
        return {
            "error": str(e),
            "correctness": 0,
            "completeness": 0,
            "safety": 0,
            "actionability": 0,
            "average": 0,
        }


def batch_judge(
    results: list[dict],
    base_url: str = DEFAULT_BASE_URL,
) -> list[dict]:
    """Judge a batch of evaluation results. Modifies results in-place."""
    for r in results:
        question = r.get("question", "")
        rag_answer = r.get("rag_answer", "")
        expected = r.get("expected_answer_keywords", [])

        if rag_answer:
            r["llm_judge"] = judge_response(question, rag_answer, expected, base_url)

        simple_answer = r.get("simple_answer", "")
        if simple_answer:
            r["llm_judge_simple"] = judge_response(question, simple_answer, expected, base_url)

    return results
