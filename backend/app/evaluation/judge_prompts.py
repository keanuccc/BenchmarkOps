"""Prompt templates for the LLM-as-Judge metric.

Each template is keyed by benchmark type and asks the judge to return exactly
one of ``MATCH`` or ``NO_MATCH`` on its own line. The judge model should be a
cheap, fast model (e.g. qwen-turbo, gpt-4o-mini) since this is called per row.

Templates are intentionally short — they only need to compare two strings, not
generate anything creative. Keeping them concise reduces cost and latency.
"""
from __future__ import annotations

JUDGE_PROMPTS: dict[str, str] = {
    "qa": """You are an impartial evaluator. Determine whether the prediction
semantically matches the expected answer.

Expected answer: {expected}
Prediction:      {prediction}

Rules:
- Treat semantically equivalent answers as a match, even if wording differs.
- Ignore case, punctuation, and minor formatting differences.
- For Chinese/English mixed content, evaluate meaning, not literal characters.
- Return ONLY "MATCH" or "NO_MATCH" on its own line. No explanation.

Output:""",

    "classification": """You are an impartial evaluator. Determine whether the
prediction selects the correct class/label compared to the expected label.

Expected label: {expected}
Prediction:     {prediction}

Rules:
- Match if the prediction clearly identifies the same class, even with extra
  commentary or different phrasing.
- Ignore surrounding text; focus on which category the prediction assigns.
- Return ONLY "MATCH" or "NO_MATCH" on its own line. No explanation.

Output:""",

    "coding": """You are an impartial evaluator. Determine whether the prediction
is a correct or acceptable solution compared to the expected answer.

Expected answer: {expected}
Prediction:      {prediction}

Rules:
- For code: consider equivalent logic, different variable names, and valid
  alternative implementations as a match.
- For text answers: same rules as QA.
- Do not penalize formatting, comments, or style differences.
- Return ONLY "MATCH" or "NO_MATCH" on its own line. No explanation.

Output:""",

    "generation": """You are an impartial evaluator. Determine whether the
prediction is semantically equivalent to the expected answer.

Expected answer: {expected}
Prediction:      {prediction}

Rules:
- Focus on meaning and factual correctness, not exact wording.
- Minor stylistic differences are acceptable.
- For summaries, check that key facts/entities from the expected answer appear
  in the prediction.
- Return ONLY "MATCH" or "NO_MATCH" on its own line. No explanation.

Output:""",

    "agent": """You are an impartial evaluator. Determine whether the prediction
achieves the expected outcome.

Expected outcome: {expected}
Prediction:       {prediction}

Rules:
- Evaluate whether the prediction satisfies the intent of the expected outcome.
- Ignore formatting, conversational filler, and presentation style.
- Return ONLY "MATCH" or "NO_MATCH" on its own line. No explanation.

Output:""",
}


def get_judge_prompt(benchmark_type: str | None) -> str:
    """Return the judge prompt template for the given benchmark type.

    Falls back to the ``qa`` template when the type is unknown or missing.
    """
    return JUDGE_PROMPTS.get(benchmark_type or "qa", JUDGE_PROMPTS["qa"])


# Default rubric dimensions per benchmark type. Each entry is
# {"name", "description"}; weights default to 1.0.
RUBRIC_DEFAULT_DIMENSIONS: dict[str, list[dict]] = {
    "qa": [
        {"name": "correctness", "description": "Whether the answer is factually correct"},
        {"name": "completeness", "description": "Whether all key points of the expected answer are covered"},
    ],
    "classification": [
        {"name": "correctness", "description": "Whether the predicted class/label matches the expected one"},
    ],
    "coding": [
        {"name": "correctness", "description": "Whether the code logic is correct and produces the expected result"},
        {"name": "completeness", "description": "Whether all requested features and edge cases are handled"},
        {"name": "quality", "description": "Code clarity, readability, and robustness"},
    ],
    "generation": [
        {"name": "correctness", "description": "Whether the content is accurate and consistent with the expected answer"},
        {"name": "completeness", "description": "Whether the key information in the expected answer is covered"},
        {"name": "coherence", "description": "Whether the text is fluent, well-structured, and easy to follow"},
    ],
    "agent": [
        {"name": "outcome", "description": "Whether the expected outcome is achieved"},
        {"name": "completeness", "description": "Whether all requirements of the expected outcome are satisfied"},
    ],
}


def build_rubric_judge_prompt(
    prediction: str,
    expected: str,
    dimensions: list[dict],
    *,
    scale: int,
    rationale: bool,
) -> str:
    """Build a judge prompt that scores each dimension from 1 to ``scale``.

    ``dimensions`` entries carry ``key`` (JSON-safe), ``name`` (display),
    ``description`` and ``weight``; the judge returns JSON of the shape
    ``{"scores": {"<key>": <1..scale>, ...}}``.
    """
    dim_lines = "\n".join(
        f"- {d['name']} ({d['key']}, 1-{scale}): {d['description'] or d['name']}"
        for d in dimensions
    )
    shape = '{"scores": {"correctness": 5, "completeness": 4}}'
    extra = ""
    if rationale:
        shape = (
            '{"scores": {"correctness": 5, "completeness": 4}, '
            '"rationale": "brief reason"}'
        )
        extra = "\n- Include a brief one-sentence rationale for the scores."
    return (
        "You are an impartial evaluator. Score the prediction against the "
        f"expected answer on each dimension from 1 to {scale} (higher is better).\n\n"
        "Expected answer:\n"
        f"{expected}\n\n"
        "Prediction:\n"
        f"{prediction}\n\n"
        "Dimensions:\n"
        f"{dim_lines}\n\n"
        "Rules:\n"
        "- Base scores strictly on evidence in the prediction.\n"
        f"- A fully correct answer must receive {scale} on every dimension.\n"
        "- Be strict but fair; assign intermediate scores when the prediction "
        "is partially correct."
        f"{extra}\n"
        "- Return ONLY valid JSON in this exact shape, with no other text:\n"
        f"{shape}\n\n"
        "Output:"
    )
