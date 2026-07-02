# QwenPipelineGuard — Devpost submission copy (Qwen Cloud Global AI Hackathon, Track 4: Autopilot Agent)

## Tagline
When a GitLab pipeline goes red, a Qwen-powered agent reads the logs like a senior engineer, pinpoints the exact root cause, and posts a diff-ready fix to your merge request — in seconds, zero clicks.

## Inspiration
Every engineer knows the 2 AM ritual: a pipeline fails, you open the job, scroll hundreds of log lines, and eventually find the one line that matters — a missing env var, a dependency clash, a flaky test. It's tedious, interrupt-driven, and scales terribly across a team. We wanted an autopilot agent that does the scrolling for us: reads the logs, isolates the *actual* cause (not "build failed"), and proposes the fix as a patch you can apply immediately.

## What it does
QwenPipelineGuard watches your GitLab CI pipelines. On every failure it:
1. **Fetches** the pipeline, its jobs, and the failing job logs through MCP tools.
2. **Reasons** over them with **Qwen (qwen-plus / qwen-max)** in an agentic tool-call loop — it decides which tools to call and when it has enough context.
3. **Produces** a structured diagnosis: the precise **root cause**, a **failure category** (env / dependency / flaky / code / config), and a **fix proposal as a unified diff** with a confidence level.
4. **Comments** the findings directly on the associated merge request, so the whole team sees them instantly.

Verified end-to-end against a real failed `gitlab-org/cli` pipeline: **~46 seconds, 2 tool calls, correct root cause identified.**

## How we built it
The core is a **dual-MCP architecture** that lets Qwen talk to GitLab through clean, typed tools instead of brittle prompt-parsing:
- **A purpose-built MCP server** (`pipelineguard.mcp_server`, stdio) exposing GitLab tools: `list_pipelines`, `get_pipeline_jobs`, `get_job_log`, `find_merge_request_by_sha`, `create_merge_request_note`.
- **The official GitLab MCP server** (Streamable HTTP, `gl_` tool prefix) for broader project/MR access.

The agent (`pipelineguard/qwen_agent.py`) runs on **Qwen via Alibaba Cloud Model Studio's OpenAI-compatible DashScope endpoint** (`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`) — no Alibaba SDK needed, just the `openai` package. MCP tools are converted from JSON Schema to OpenAI function-calling format, the loop is bounded (≤15 iterations), and it returns a schema-validated `DiagnosisReport`. It's wrapped in a **FastAPI** webhook server (`/webhook/gitlab`, `/demo`, `/health`) and deploys to Alibaba Cloud ECS.

## Challenges we ran into
Porting the agent from a Gemini backend to Qwen's tool-calling loop meant reconciling function-call formats and streaming quirks, and keeping the diagnosis output schema-stable across models. Converting MCP JSON-Schema tools into OpenAI-compatible function definitions that Qwen calls reliably took iteration.

## Accomplishments that we're proud of
It's not a toy demo — it ran end-to-end on a real failed pipeline in `gitlab-org/cli` and found the correct root cause in ~46 seconds using just 2 tool calls. It's read-only on your repo (it proposes, it doesn't push), and the whole diagnosis is powered by Qwen on Alibaba Cloud.

## What we learned
MCP is a clean seam for giving an LLM real, typed access to a system of record (GitLab), and Qwen's OpenAI-compatible endpoint makes it a drop-in agentic reasoner with no vendor SDK lock-in.

## What's next for QwenPipelineGuard
Multi-provider CI (GitHub Actions, CircleCI), auto-opening fix MRs behind human approval, and a historical "why did this break before?" memory over past diagnoses.

## Built with
python, qwen, alibaba-cloud, dashscope, model-context-protocol, fastapi, gitlab, openai

## Proof of deployment
- **Code file using Qwen Cloud APIs:** `pipelineguard/qwen_agent.py` and `docs/alibaba-cloud-proof.py` (both call the DashScope compatible-mode endpoint).
- **Screenshot of running resources on Alibaba Cloud:** Qwen Cloud / Model Studio console (attached).
