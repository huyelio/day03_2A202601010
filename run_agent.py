import argparse
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.core.provider_factory import create_provider
from src.agent.agent import ReActAgent
from src.agent.agent_v2 import ReActAgentV2

try:
    from src.tools.educourse_tools import TOOLS
except ImportError:
    from src.tools.educourse_mock_tools import TOOLS


DEFAULT_QUERY = (
    "Em muốn học Python beginner vào buổi tối, ngân sách khoảng 1.500.000 VND. "
    "Còn lớp nào phù hợp không và học phí sau mã STUDENT10 là bao nhiêu?"
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run EduCourse ReAct Agent with selected LLM provider."
    )

    parser.add_argument(
        "--provider",
        choices=["openai", "gemini", "google"],
        default=None,
        help="LLM provider to use. Example: openai or gemini.",
    )

    parser.add_argument(
        "--model",
        default=None,
        help="Optional model override. Example: gpt-4o or gemini-2.5-flash.",
    )

    parser.add_argument(
        "--query",
        default=DEFAULT_QUERY,
        help="User query for the agent.",
    )

    parser.add_argument(
        "--agent-version",
        choices=["v1", "v2"],
        default="v2",
        help="Agent logic version. v2 recovers common Action formatting errors.",
    )

    parser.add_argument(
        "--max-steps",
        type=int,
        default=6,
        help="Maximum ReAct reasoning steps.",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    llm = create_provider(
        provider_name=args.provider,
        model_name=args.model,
    )

    agent_class = ReActAgentV2 if args.agent_version == "v2" else ReActAgent
    agent = agent_class(
        llm=llm,
        tools=TOOLS,
        max_steps=args.max_steps,
    )

    tool_names = [tool["name"] for tool in TOOLS]

    print("\n=== RUN CONFIG ===")
    print(f"Provider model: {llm.model_name}")
    print(f"Available tools: {', '.join(tool_names)}")
    print(f"Max steps: {args.max_steps}")
    print(f"Agent version: {args.agent_version}")
    print(f"Query: {args.query}")

    answer = agent.run(args.query)

    print("\n=== FINAL ANSWER ===")
    print(answer)


if __name__ == "__main__":
    main()
