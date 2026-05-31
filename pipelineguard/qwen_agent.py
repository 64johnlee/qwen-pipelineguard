"""QwenPipelineGuard agent — replaces Gemini with Qwen via OpenAI-compatible API."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import anyio
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from .backends.direct import DirectBackend
from .backends.gitlab_mcp import GitLabOfficialMCPBackend
from .backends.mcp import MCPBackend
from .models import Confidence, DiagnosisReport, FailureCategory, FixProposal
from .prompts import SYSTEM_PROMPT, build_analysis_prompt

try:
    from mcp.types import Tool as MCPTool
except ImportError:
    MCPTool = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)
console = Console()

_QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen-plus")
_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_MAX_TOOL_ITERATIONS = 15


def _mcp_to_openai_tool(tool: Any) -> dict[str, Any]:
    """Convert an MCP Tool to OpenAI function-calling format."""
    schema = tool.inputSchema or {}
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": {
                "type": "object",
                "properties": schema.get("properties", {}),
                "required": schema.get("required", []),
            },
        },
    }


async def _list_tools_as_openai(backend: MCPBackend | GitLabOfficialMCPBackend) -> list[dict]:
    """Get tools from an MCP backend in OpenAI format."""
    from mcp.types import Tool as MCPTool  # noqa: F811
    result = await backend._session.list_tools()  # type: ignore[attr-defined]
    return [_mcp_to_openai_tool(t) for t in result.tools]


class QwenPipelineGuardAgent:
    """
    Diagnoses GitLab CI pipeline failures using Qwen (via OpenAI-compatible API).

    Drop-in replacement for PipelineGuardAgent — same MCP tool-call loop,
    same backends, same DiagnosisReport output. Only the LLM is different.
    """

    def __init__(
        self,
        gitlab_token: str,
        qwen_api_key: str = "",
        gitlab_url: str = "https://gitlab.com",
        force_direct: bool = False,
    ) -> None:
        self._client = OpenAI(
            api_key=qwen_api_key or os.environ.get("DASHSCOPE_API_KEY", ""),
            base_url=_QWEN_BASE_URL,
        )
        self._gitlab_token = gitlab_token
        self._gitlab_url = gitlab_url
        self._use_mcp = (not force_direct) and MCPBackend.is_available()

    async def diagnose(
        self,
        project: str,
        pipeline_id: int | None = None,
        post_comment: bool = False,
    ) -> DiagnosisReport:
        mode = "MCP (Qwen + GitLab MCP)" if self._use_mcp else "direct"
        console.print(
            Panel(
                f"[bold cyan]QwenPipelineGuard[/] · [green]{project}[/]"
                + (f" · pipeline [yellow]#{pipeline_id}[/]" if pipeline_id else " · latest failed")
                + f"\n[dim]model: {_QWEN_MODEL} · mode: {mode}[/]",
                border_style="cyan",
            )
        )
        if self._use_mcp:
            return await self._diagnose_mcp(project, pipeline_id, post_comment)
        return await self._diagnose_direct(project, pipeline_id, post_comment)

    async def _diagnose_mcp(
        self,
        project: str,
        pipeline_id: int | None,
        post_comment: bool,
    ) -> DiagnosisReport:
        async with MCPBackend(self._gitlab_token, self._gitlab_url) as pipeline_backend:
            async with GitLabOfficialMCPBackend(self._gitlab_token, self._gitlab_url) as official_backend:
                pipeline_tools = await _list_tools_as_openai(pipeline_backend)
                official_tools = (
                    await _list_tools_as_openai(official_backend)
                    if official_backend.connected
                    else []
                )
                all_tools = pipeline_tools + official_tools

                prompt = build_analysis_prompt(project=project, pipeline_id=pipeline_id)
                messages: list[dict] = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ]
                final_text = await self._run_tool_loop(
                    pipeline_backend, official_backend, all_tools, messages
                )
        return _parse_report(final_text, project, pipeline_id)

    async def _run_tool_loop(
        self,
        pipeline_backend: MCPBackend,
        official_backend: GitLabOfficialMCPBackend,
        tools: list[dict],
        messages: list[dict],
    ) -> str:
        final_text = ""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task_id = progress.add_task("Thinking…", total=None)

            for iteration in range(1, _MAX_TOOL_ITERATIONS + 1):
                progress.update(task_id, description=f"Iteration {iteration}/{_MAX_TOOL_ITERATIONS}…")

                response = await anyio.to_thread.run_sync(
                    lambda: self._client.chat.completions.create(
                        model=_QWEN_MODEL,
                        messages=messages,
                        tools=tools if tools else None,  # type: ignore[arg-type]
                        temperature=0.1,
                    )
                )

                choice = response.choices[0]
                msg = choice.message
                messages.append(msg.model_dump(exclude_unset=True))

                if msg.content:
                    final_text = msg.content

                tool_calls = msg.tool_calls or []
                if not tool_calls:
                    break

                for tc in tool_calls:
                    fn = tc.function
                    args = json.loads(fn.arguments or "{}")
                    progress.update(task_id, description=f"→ {fn.name}(…)")
                    console.print(f"  [dim]→ {fn.name}({json.dumps(args)[:80]})[/]")

                    if official_backend.owns_tool(fn.name):
                        result_text = await official_backend.call_tool(fn.name, args)
                    else:
                        result_text = await pipeline_backend.call_tool(fn.name, args)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_text,
                    })

        return final_text

    async def _diagnose_direct(
        self,
        project: str,
        pipeline_id: int | None,
        post_comment: bool,
    ) -> DiagnosisReport:
        backend = DirectBackend(self._gitlab_token, self._gitlab_url)
        console.print("[dim]Fetching pipeline data from GitLab…[/]")
        data = await anyio.to_thread.run_sync(
            lambda: backend.get_failed_pipeline_data(project, pipeline_id)
        )
        prompt = f"Analyse this GitLab CI failure:\n\n{json.dumps(data, indent=2)}"
        console.print(f"[dim]Sending to {_QWEN_MODEL} for analysis…[/]")

        response = await anyio.to_thread.run_sync(
            lambda: self._client.chat.completions.create(
                model=_QWEN_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.1,
            )
        )
        final_text = response.choices[0].message.content or ""
        return _parse_report(final_text, project, data.get("pipeline_id") or pipeline_id)


# ---------------------------------------------------------------------------
# Report parsing (identical to agent.py)
# ---------------------------------------------------------------------------

def _parse_report(
    text: str,
    project: str,
    pipeline_id: int | None,
) -> DiagnosisReport:
    """Extract a DiagnosisReport from the LLM's final text output."""
    import re
    brace = text.rfind("{")
    if brace != -1:
        candidate = text[brace:]
        depth = 0
        end = -1
        for i, ch in enumerate(candidate):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > 0:
            raw = re.sub(r"[\x00-\x1F\x7F]", " ", candidate[:end])
            try:
                parsed = json.loads(raw)
                return DiagnosisReport(
                    project=project,
                    pipeline_id=pipeline_id,
                    root_cause=parsed.get("root_cause", ""),
                    failure_category=FailureCategory(
                        parsed.get("failure_category", "unknown")
                    ) if parsed.get("failure_category") in [e.value for e in FailureCategory] else FailureCategory.UNKNOWN,
                    fix_proposals=[
                        FixProposal(
                            file=fp.get("file", ""),
                            description=fp.get("description", ""),
                            diff=fp.get("diff", ""),
                            confidence=Confidence(fp.get("confidence", "low"))
                            if fp.get("confidence") in [e.value for e in Confidence] else Confidence.LOW,
                        )
                        for fp in parsed.get("fix_proposals", [])
                    ],
                    full_analysis=text,
                )
            except (json.JSONDecodeError, ValueError):
                pass
    return DiagnosisReport(
        project=project,
        pipeline_id=pipeline_id,
        root_cause=text[:500] if text else "No analysis returned",
        failure_category=FailureCategory.UNKNOWN,
        fix_proposals=[],
        full_analysis=text,
    )
