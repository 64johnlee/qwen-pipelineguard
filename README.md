# QwenPipelineGuard

> AI-powered GitLab CI pipeline diagnostics using **Qwen** (via Qwen Cloud) + a purpose-built MCP server.

**Submitted to the [Global AI Hackathon with Qwen Cloud](https://qwencloud-hackathon.devpost.com/) — Track 4: Autopilot Agent.**

QwenPipelineGuard watches your GitLab CI pipelines. When one fails, it:

1. **Fetches** job logs via a bundled stdio MCP server (`pipelineguard.mcp_server`)
2. **Analyses** root cause with **Qwen** (qwen-plus / qwen-max) in an agentic tool-call loop
3. **Proposes** a targeted fix with a unified diff
4. **Comments** the findings on the associated merge request

Verified end-to-end against a real failed `gitlab-org/cli` pipeline: **~46 seconds, 2 tool calls, correct root cause identified.**

## Architecture

```
GitLab Pipeline Fails
        │
        ▼  POST /webhook/gitlab
QwenPipelineGuard / FastAPI
        │
        ├── Qwen (via Qwen Cloud / DashScope OpenAI-compatible API)
        │   └── agentic tool-call loop (≤15 iterations)
        │
        ├── PipelineGuard MCP Server (stdio, bundled)
        │   └── list_pipelines, get_pipeline_jobs, get_job_log, ...
        │
        └── Official GitLab MCP Server (StreamableHTTP)
            └── gl_list_projects, gl_get_pipeline, ...
```

## Quick Start

```bash
git clone https://github.com/64johnlee/qwen-pipelineguard
cd qwen-pipelineguard
pip install -e ".[web]"
cp .env.example .env  # add DASHSCOPE_API_KEY + GITLAB_TOKEN

# One-shot diagnosis
python -m pipelineguard.qwen_cli myorg/myrepo

# Webhook server
pipelineguard serve
```

## Key Files

| File | Purpose |
|---|---|
| `pipelineguard/qwen_agent.py` | Qwen agent — OpenAI-compatible tool-call loop |
| `pipelineguard/agent.py` | Original Gemini agent (kept for reference) |
| `pipelineguard/backends/mcp.py` | PipelineGuard MCP server client |
| `pipelineguard/backends/gitlab_mcp.py` | Official GitLab MCP server client |
| `pipelineguard/webhook.py` | FastAPI webhook server |

## Qwen vs Gemini

The Qwen agent (`qwen_agent.py`) uses the OpenAI-compatible API at `dashscope.aliyuncs.com/compatible-mode/v1` — no Alibaba Cloud SDK required, just `openai` Python package. MCP tools are converted from JSON Schema to OpenAI function format. The rest of the architecture (MCP backends, FastAPI server, DiagnosisReport schema) is unchanged.

## Deployment on Alibaba Cloud

See [`deploy_alibaba.sh`](deploy_alibaba.sh) for ECS deployment.

## License

MIT
