import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tests.evaluation.test_cases import get_test_cases
from src.chatbot import ChatbotBaseline
from src.core.llm_provider import LLMProvider


RESULTS_DIR = ROOT_DIR / "tests" / "evaluation" / "results"


def build_provider(provider: str, model: Optional[str] = None) -> LLMProvider:
    if provider == "openai":
        from src.core.openai_provider import OpenAIProvider

        return OpenAIProvider(
            model_name=model or os.getenv("DEFAULT_MODEL", "gpt-4o-mini"),
            api_key=os.getenv("OPENAI_API_KEY"),
        )

    if provider in {"gemini", "google"}:
        from src.core.gemini_provider import GeminiProvider

        return GeminiProvider(
            model_name=model or os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
            api_key=os.getenv("GEMINI_API_KEY"),
        )

    raise ValueError(f"Unsupported provider: {provider}")


def load_tools() -> List[Dict[str, Any]]:
    try:
        from src.tools.educourse_tools import TOOLS

        return TOOLS
    except Exception:
        return []


def build_agent(agent_version: str, llm: LLMProvider):
    tools = load_tools()
    if not tools:
        return None, "EduCourse tools are not available yet."

    try:
        if agent_version == "agent_v2":
            from src.agent.agent_v2 import ReActAgentV2

            return ReActAgentV2(llm=llm, tools=tools), None

        from src.agent.agent import ReActAgent

        return ReActAgent(llm=llm, tools=tools), None
    except Exception as exc:
        return None, str(exc)


def normalize_text(text: str) -> str:
    text = text.lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(
        character
        for character in text
        if unicodedata.category(character) != "Mn"
    )
    return re.sub(r"\s+", " ", text).strip()


def contains_any(text: str, terms: List[str]) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(term) in normalized for term in terms)


def states_no_slots(text: str) -> bool:
    normalized = normalize_text(text)
    return (
        contains_any(text, ["het cho", "khong con cho", "0", "zero"])
        or ("khong co" in normalized and "con cho" in normalized)
    )


def evaluate_answer(case_id: str, answer: str) -> Dict[str, Any]:
    checks = {
        "simple_001": [
            (
                "mentions_courses",
                contains_any(
                    answer,
                    ["python", "web", "data science", "ai101", "ai for beginners"],
                ),
            ),
        ],
        "course_001": [
            ("mentions_python_beginner", contains_any(answer, ["py101", "python beginner"])),
            ("mentions_discount", contains_any(answer, ["student10", "10%"])),
            ("mentions_final_tuition", contains_any(answer, ["1,350,000", "1350000", "1.350.000"])),
        ],
        "course_002": [
            ("mentions_web_course", contains_any(answer, ["web101", "web development", "web beginner"])),
            ("states_no_slots", states_no_slots(answer)),
        ],
        "course_003": [
            ("mentions_data_science", contains_any(answer, ["ds101", "data science"])),
            ("mentions_tuition", contains_any(answer, ["2,500,000", "2500000", "2.500.000"])),
            ("mentions_over_budget", contains_any(answer, ["vượt", "cao hơn", "không phù hợp", "exceeds"])),
        ],
        "course_004": [
            ("mentions_ai_course", contains_any(answer, ["ai101", "ai for beginners", "ai beginner"])),
            ("mentions_discount", contains_any(answer, ["earlybird", "15%"])),
            ("mentions_final_tuition", contains_any(answer, ["1,530,000", "1530000", "1.530.000"])),
        ],
        "failure_001": [
            ("rejects_fake_coupon", contains_any(answer, ["fakecode", "không hợp lệ", "invalid"])),
            ("does_not_fake_discount", not contains_any(answer, ["fakecode hợp lệ", "giảm 10", "giảm 15"])),
        ],
    }

    case_checks = checks.get(case_id, [])
    passed_checks = [name for name, passed in case_checks if passed]
    failed_checks = [name for name, passed in case_checks if not passed]

    return {
        "passed": bool(case_checks) and not failed_checks,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "needs_human_review": bool(failed_checks),
    }


def extract_common_metrics(raw_result: Dict[str, Any], elapsed_ms: int) -> Dict[str, Any]:
    usage = raw_result.get("usage") or {}
    return {
        "latency_ms": raw_result.get("latency_ms", elapsed_ms),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


def run_baseline_case(case: Dict[str, Any], llm: LLMProvider) -> Dict[str, Any]:
    bot = ChatbotBaseline(llm)
    start = time.time()
    raw_result = bot.run(case["query"])
    elapsed_ms = int((time.time() - start) * 1000)
    answer = raw_result.get("answer", "")

    return {
        "id": case["id"],
        "target": "chatbot",
        "query": case["query"],
        "expected": case["expected"],
        "expected_tools": case["expected_tools"],
        "answer": answer,
        "status": "completed",
        "correctness": evaluate_answer(case["id"], answer),
        "metrics": {
            **extract_common_metrics(raw_result, elapsed_ms),
            "steps": 0,
            "parser_errors": 0,
            "hallucinated_tool_errors": 0,
            "timeouts": 0,
            "tool_errors": 0,
        },
    }


def run_agent_case(case: Dict[str, Any], llm: LLMProvider, agent_version: str) -> Dict[str, Any]:
    agent, skip_reason = build_agent(agent_version, llm)
    if agent is None:
        return {
            "id": case["id"],
            "target": agent_version,
            "query": case["query"],
            "expected": case["expected"],
            "expected_tools": case["expected_tools"],
            "answer": "",
            "status": "skipped",
            "skip_reason": skip_reason,
            "correctness": {
                "passed": False,
                "passed_checks": [],
                "failed_checks": [],
                "needs_human_review": True,
            },
            "metrics": {
                "latency_ms": None,
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "steps": None,
                "parser_errors": None,
                "hallucinated_tool_errors": None,
                "timeouts": None,
                "tool_errors": None,
            },
        }

    start = time.time()
    try:
        answer = agent.run(case["query"])
        status = "completed"
        error = None
    except Exception as exc:
        answer = ""
        status = "error"
        error = str(exc)
    elapsed_ms = int((time.time() - start) * 1000)
    history = getattr(agent, "history", [])
    usage_rows = [item.get("usage") or {} for item in history]

    def total_usage(metric_name: str) -> Optional[int]:
        values = [usage.get(metric_name) for usage in usage_rows]
        clean_values = [value for value in values if value is not None]
        return sum(clean_values) if clean_values else None

    return {
        "id": case["id"],
        "target": agent_version,
        "query": case["query"],
        "expected": case["expected"],
        "expected_tools": case["expected_tools"],
        "answer": answer,
        "status": status,
        "error": error,
        "correctness": evaluate_answer(case["id"], answer),
        "metrics": {
            "latency_ms": elapsed_ms,
            "prompt_tokens": total_usage("prompt_tokens"),
            "completion_tokens": total_usage("completion_tokens"),
            "total_tokens": total_usage("total_tokens"),
            "steps": len(history) or None,
            "parser_errors": None,
            "hallucinated_tool_errors": None,
            "timeouts": None,
            "tool_errors": None,
        },
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def write_markdown(path: Path, results: List[Dict[str, Any]]) -> None:
    lines = [
        "| Case | Target | Status | Passed | Latency ms | Total tokens | Notes |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for item in results:
        correctness = item["correctness"]
        metrics = item["metrics"]
        notes = item.get("skip_reason") or item.get("error") or ", ".join(correctness["failed_checks"])
        lines.append(
            "| {case} | {target} | {status} | {passed} | {latency} | {tokens} | {notes} |".format(
                case=item["id"],
                target=item["target"],
                status=item["status"],
                passed="yes" if correctness["passed"] else "no",
                latency=metrics.get("latency_ms") if metrics.get("latency_ms") is not None else "",
                tokens=metrics.get("total_tokens") if metrics.get("total_tokens") is not None else "",
                notes=notes.replace("|", "/"),
            )
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_evaluation(target: str, provider: str, model: Optional[str]) -> List[Dict[str, Any]]:
    llm = build_provider(provider, model)
    cases = get_test_cases()
    results = []

    targets = ["baseline", "agent_v1", "agent_v2"] if target == "all" else [target]
    for current_target in targets:
        for case in cases:
            print(f"Running {current_target}: {case['id']}")
            if current_target == "baseline":
                results.append(run_baseline_case(case, llm))
            else:
                results.append(run_agent_case(case, llm, current_target))

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run EduCourse chatbot/agent evaluation cases.")
    parser.add_argument("--target", choices=["baseline", "agent_v1", "agent_v2", "all"], default="baseline")
    parser.add_argument("--provider", choices=["openai", "gemini", "google"], default=os.getenv("DEFAULT_PROVIDER", "openai"))
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    load_dotenv(ROOT_DIR / ".env")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results = run_evaluation(args.target, args.provider, args.model)

    result_prefix = f"{args.target}_{args.provider}_{timestamp}"
    json_path = RESULTS_DIR / f"{result_prefix}.json"
    markdown_path = RESULTS_DIR / f"{result_prefix}.md"
    write_json(json_path, results)
    write_markdown(markdown_path, results)

    print(f"Saved JSON results to {json_path}")
    print(f"Saved Markdown summary to {markdown_path}")


if __name__ == "__main__":
    main()
