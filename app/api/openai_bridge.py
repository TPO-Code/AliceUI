from __future__ import annotations
import json
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI  # pip install openai
from toolserver_client import ToolServerClient, Message


def _tool_calls_as_message_dicts(tool_calls_obj) -> List[Dict[str, Any]]:
    """
    Convert OpenAI SDK tool_call objects into the dict shape the API expects
    when you append them into messages for the finalization call.
    """
    out = []
    for tc in (tool_calls_obj or []):
        # tc has fields: id, type="function", function={ name, arguments }
        out.append({
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments,  # JSON string per API
            },
        })
    return out


def _safe_parse_arguments(arg_str: Optional[str]) -> Dict[str, Any]:
    if not arg_str:
        return {}
    try:
        return json.loads(arg_str)
    except Exception:
        # Fall back to pass-through if model produced non-JSON
        return {"_raw_arguments": arg_str}


class OpenAIWithToolServer:
    """
    Non-streaming, two-pass OpenAI bridge that:
      1) discovers tools from your Tool Server based on conversation context,
      2) sends chat.completions with those tools,
      3) executes any tool calls on the Tool Server (batch if available),
      4) sends a finalizing chat.completions request.

    - Supports multiple tool calls in one assistant message.
    - Falls back to per-call /execute if /execute/batch is unavailable.
    """

    def __init__(
        self,
        openai_client: OpenAI,
        toolserver: ToolServerClient,
        model: str,
        tool_choice: str | Dict[str, Any] = "auto",
        default_k_tools: int = 8,
        system_prompt: Optional[str] = None,
        try_batch_execute: bool = True,
        parallel_batch: bool = False,  # keep sequential by default (deterministic order)
    ):
        self.client = openai_client
        self.ts = toolserver
        self.model = model
        self.tool_choice = tool_choice
        self.default_k_tools = default_k_tools
        self.system_prompt = system_prompt
        self.try_batch_execute = try_batch_execute
        self.parallel_batch = parallel_batch

    # ---------- OpenAI calls ----------
    def _first_call(self, messages: List[Message], tools: List[Dict[str, Any]]):
        return self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice=self.tool_choice,
            # parallel_tool_calls=True,  # optional toggle
        )

    def _final_call(self, messages: List[Message]):
        return self.client.chat.completions.create(
            model=self.model,
            messages=messages
        )

    def _prepend_system(self, messages: List[Message]) -> List[Message]:
        if self.system_prompt:
            return [{"role": "system", "content": self.system_prompt}, *messages]
        return messages

    # ---------- Public API ----------
    def run_one_turn(
        self,
        conversation_id: str,
        messages: List[Message],
        k_tools: Optional[int] = None,
        force_refresh_tools: bool = False,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Returns:
            (final_assistant_text, debug_details)
        """
        # 1) Discover tools from Tool Server
        tools, alias_map = self.ts.build_openai_tools(
            conversation_id, messages, k_tools or self.default_k_tools, force_refresh=force_refresh_tools
        )

        msgs = self._prepend_system(messages)

        # 2) First OpenAI call
        first = self._first_call(msgs, tools)
        first_msg = first.choices[0].message

        if not getattr(first_msg, "tool_calls", None):
            # No tools requested
            return (first_msg.content or "", {
                "phase": "no_tool_calls",
                "alias_map": alias_map,
                "first_response": first.to_dict() if hasattr(first, "to_dict") else None,
            })

        # 3) Execute tool calls (batch if possible)
        tool_calls = first_msg.tool_calls
        assistant_msg_for_log = {
            "role": "assistant",
            "content": first_msg.content,
            "tool_calls": _tool_calls_as_message_dicts(tool_calls),
        }
        msgs_with_tools: List[Message] = msgs + [assistant_msg_for_log]

        # build batch payload for server
        calls_payload: List[Dict[str, Any]] = []
        for tc in tool_calls:
            calls_payload.append({
                "function": tc.function.name,
                "arguments": _safe_parse_arguments(tc.function.arguments),
                "tool_call_id": tc.id,
            })

        tool_results = []
        batch_ok = False

        if self.try_batch_execute and len(calls_payload) > 1:
            try:
                batch_resp = self.ts.execute_batch(conversation_id, calls_payload, parallel=self.parallel_batch)
                for r in batch_resp.get("results", []):
                    tool_results.append(r)
                    msgs_with_tools.append({
                        "role": "tool",
                        "tool_call_id": r.get("tool_call_id"),
                        "name": r.get("function"),
                        "content": r.get("content") if r.get("ok") else json.dumps(r),
                    })
                batch_ok = True
            except Exception as e:
                # Fall back to sequential one-by-one execute
                tool_results.append({"_batch_error": str(e)})

        if not batch_ok:
            # sequential fallback or single-call path
            for call in calls_payload:
                exec_res = self.ts.execute(
                    conversation_id=conversation_id,
                    function=call["function"],
                    arguments=call["arguments"],
                    tool_call_id=call.get("tool_call_id"),
                )
                tool_results.append({"tool_call_id": call.get("tool_call_id"),
                                     "function": call["function"],
                                     **exec_res})
                msgs_with_tools.append({
                    "role": "tool",
                    "tool_call_id": call.get("tool_call_id"),
                    "name": call["function"],
                    "content": exec_res.get("content") if exec_res.get("ok") else json.dumps(exec_res),
                })

        # 4) Final OpenAI call
        final = self._final_call(msgs_with_tools)
        final_msg = final.choices[0].message
        return (final_msg.content or "", {
            "phase": "tool_calls_executed",
            "alias_map": alias_map,
            "first_response": first.to_dict() if hasattr(first, "to_dict") else None,
            "final_response": final.to_dict() if hasattr(final, "to_dict") else None,
            "tool_results": tool_results,
        })
