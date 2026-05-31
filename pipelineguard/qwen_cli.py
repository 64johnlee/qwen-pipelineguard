"""CLI entry point for QwenPipelineGuard."""
import asyncio
import os
import click
from .qwen_agent import QwenPipelineGuardAgent

@click.command()
@click.argument("project")
@click.option("--pipeline-id", "-p", type=int, default=None)
@click.option("--comment/--no-comment", default=False)
@click.option("--direct", is_flag=True)
def diagnose(project: str, pipeline_id: int | None, comment: bool, direct: bool) -> None:
    """Diagnose a GitLab CI pipeline failure using Qwen."""
    agent = QwenPipelineGuardAgent(
        gitlab_token=os.environ["GITLAB_TOKEN"],
        qwen_api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        force_direct=direct,
    )
    report = asyncio.run(agent.diagnose(project, pipeline_id, comment))
    click.echo(f"\nRoot cause: {report.root_cause}")
    click.echo(f"Category:   {report.failure_category.value}")
    for fp in report.fix_proposals:
        click.echo(f"\n[{fp.confidence.value}] {fp.description}")
        if fp.diff:
            click.echo(fp.diff[:800])

if __name__ == "__main__":
    diagnose()
