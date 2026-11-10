"""No-tools, no-system-prompt baseline for Project 2 README comparisons.

Run from the same project directory/environment used by app.py:
    uv run python baseline.py --all
    uv run python baseline.py --question "Does niacinamide help with acne?"
    uv run python baseline.py  # enter one question interactively

Each query is an independent, single-turn request. This script intentionally
passes NO system prompt, NO tools and NO previous conversation history.
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path

import litellm
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

# Matches the Lead and Writer model in Project 2's app.py.
MODEL = "vertex_ai/gemini-3.5-flash"
VERTEX_LOCATION = "global"

# Edit this list to use the exact three sample queries in your README.
SAMPLE_QUERIES = [
    "What's in Clinique Moisture Surge 100H? I don't really understand skincare ingredients. Can you explain what they do?",
    "Olay Retinol24 says its retinol and vitamin B3 can help reduce wrinkles and dark spots. Does that stuff actually work, or is it just marketing?",
    "I've heard retinol can irritate your skin. Is Olay Retinol24 actually safe to use? Could any of its ingredients cause problems?",
]


def get_baseline_answer(question: str) -> str:
    """One independent model call, with only the user's question."""
    result = litellm.completion(
        model=MODEL,
        vertex_location=VERTEX_LOCATION,
        messages=[{"role": "user", "content": question}],
        # Deliberately no `tools`, `system` role or earlier messages.
        timeout=90,
        num_retries=2,
    )
    return result.choices[0].message.content or "[Model returned an empty answer]"


def make_markdown(questions: list[str]) -> str:
    created = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sections = [
        "# No-tools baseline results",
        "",
        f"Model: `{MODEL}`  ",
        f"Generated: {created}  ",
        "Setup: single-turn user message only; no system prompt, no tools, no conversation history.",
    ]
    for i, question in enumerate(questions, 1):
        print(f"Running baseline {i}/{len(questions)}: {question}", flush=True)
        answer = get_baseline_answer(question)
        sections.extend(["", f"## Query {i}", "", f"**Question:** {question}", "", "**Baseline answer:**", "", answer, ""])
    return "\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run no-tools Gemini baseline(s) for Project 2")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="Run the three queries in SAMPLE_QUERIES")
    group.add_argument("--question", type=str, help="Run exactly one specified question")
    parser.add_argument("--output", default="baseline_results.md", help="Markdown output path")
    args = parser.parse_args()

    if args.all:
        questions = SAMPLE_QUERIES
    elif args.question is not None:
        questions = [args.question]
    else:
        question = input("Enter the exact question to test: ").strip()
        if not question:
            parser.error("Question cannot be empty")
        questions = [question]

    markdown = make_markdown(questions)
    output = Path(args.output)
    output.write_text(markdown, encoding="utf-8")
    print(f"\nSaved {len(questions)} answer(s) to {output.resolve()}")


if __name__ == "__main__":
    main()
