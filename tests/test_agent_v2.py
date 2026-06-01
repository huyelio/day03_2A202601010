from typing import Dict, Generator, List, Optional

from src.agent.agent import ReActAgent
from src.agent.agent_v2 import ReActAgentV2
from src.core.llm_provider import LLMProvider
from src.tools.educourse_tools import TOOLS


class ScriptedProvider(LLMProvider):
    def __init__(self, responses: List[str]):
        super().__init__(model_name="scripted-test-model")
        self.responses = iter(responses)

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> Dict:
        return {
            "content": next(self.responses),
            "provider": "scripted",
            "usage": {},
            "latency_ms": 0,
        }

    def stream(
        self, prompt: str, system_prompt: Optional[str] = None
    ) -> Generator[str, None, None]:
        yield self.generate(prompt, system_prompt)["content"]


def test_v1_parser_rejects_python_style_action_arguments():
    agent = ReActAgent(llm=ScriptedProvider([]), tools=TOOLS)

    assert agent._parse_action("Action: search_courses({'topic': 'Python'})") is None


def test_v2_parser_recovers_python_style_action_arguments():
    agent = ReActAgentV2(llm=ScriptedProvider([]), tools=TOOLS)

    assert agent._parse_action("Action: search_courses({'topic': 'Python'})") == (
        "search_courses",
        {"topic": "Python"},
    )


def test_v2_executes_repaired_action_and_finishes():
    llm = ScriptedProvider(
        [
            "Thought: Search the catalog.\n"
            "Action: search_courses({'topic': 'Python', 'level': 'beginner'})",
            "Final Answer: PY101 - Python Beginner is available.",
        ]
    )
    agent = ReActAgentV2(llm=llm, tools=TOOLS, max_steps=2)

    answer = agent.run("Find a beginner Python course.")

    assert answer == "PY101 - Python Beginner is available."
    assert len(agent.history) == 2
