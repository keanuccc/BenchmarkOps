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
