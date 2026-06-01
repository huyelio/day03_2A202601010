import ast
import json
import re
from typing import Any, Dict, Optional, Tuple

from src.agent.agent import ReActAgent
from src.telemetry.logger import logger


class ReActAgentV2(ReActAgent):
    """
    ReAct Agent v2 with a recovery path for common LLM Action formatting errors.
    """

    def get_system_prompt(self) -> str:
        return (
            super()
            .get_system_prompt()
            .replace("EduCourse ReAct Agent v1", "EduCourse ReAct Agent v2")
            + "\n- Output Action arguments as one raw JSON object with double-quoted keys and values."
        )

    def _parse_action(self, content: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        parsed_action = super()._parse_action(content)
        if parsed_action is not None:
            return parsed_action

        cleaned = self._strip_markdown_fences(content)
        match = re.search(
            r"Action\s*:\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\((.*)\)",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return None

        tool_name = match.group(1).strip()
        args_text = re.split(
            r"\n\s*(Observation|Final Answer)\s*:",
            match.group(2).strip(),
            flags=re.IGNORECASE,
        )[0].strip()

        args = self._recover_dict(args_text)
        if args is None:
            return None

        logger.log_event(
            "AGENT_V2_ACTION_REPAIRED",
            {
                "tool_name": tool_name,
                "original_args": args_text,
                "repaired_args": args,
            },
        )
        return tool_name, args

    def _recover_dict(self, args_text: str) -> Optional[Dict[str, Any]]:
        candidate = self._extract_braced_object(args_text)
        if candidate is None:
            return None

        try:
            args = ast.literal_eval(candidate)
        except (SyntaxError, ValueError):
            return None

        if not isinstance(args, dict):
            return None

        try:
            json.dumps(args)
        except (TypeError, ValueError):
            return None

        return args

    def _extract_braced_object(self, text: str) -> Optional[str]:
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        quote = None
        escaped = False
        for index in range(start, len(text)):
            character = text[index]
            if escaped:
                escaped = False
                continue
            if character == "\\":
                escaped = True
                continue
            if quote:
                if character == quote:
                    quote = None
                continue
            if character in {"'", '"'}:
                quote = character
                continue
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]

        return None
