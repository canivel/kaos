"""Interactive setup wizard for KAOS.

Guides the user through configuring kaos.yaml by asking 3 simple questions:
  1. How do you want to use KAOS? (Claude Code only / local models / cloud APIs / hybrid)
  2. Which models? (select from presets or enter custom)
  3. Confirm and write config

Usage:
    kaos setup
"""

from __future__ import annotations

import os
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

console = Console()

# ── Preset configurations ────────────────────────────────────────

PRESETS = {
    "claude-code": {
        "description": "Use KAOS with Claude Code only (no extra LLM config needed)",
        "detail": "KAOS provides isolation, checkpoints, and audit trails. Claude Code handles all LLM calls via MCP.",
        "config": {
            "database": {"path": "./kaos.db", "wal_mode": True, "compression": "zstd"},
            "ccr": {
                "max_iterations": 100,
                "checkpoint_interval": 10,
                "max_parallel_agents": 8,
            },
        },
    },
    "local": {
        "description": "Run everything locally with open-source models (vLLM/ollama)",
        "detail": "Point KAOS at your local vLLM or ollama instance. GEPA routes tasks to the right model. Zero API costs.",
        "config": {
            "database": {"path": "./kaos.db", "wal_mode": True, "compression": "zstd"},
            "models": {
                "local-model": {
                    "provider": "local",
                    "endpoint": "http://localhost:8000/v1",
                    "max_context": 32768,
                    "use_for": ["trivial", "moderate", "complex", "critical"],
                },
            },
            "router": {
                "fallback_model": "local-model",
                "context_compression": True,
            },
            "ccr": {
                "max_iterations": 100,
                "checkpoint_interval": 10,
                "max_parallel_agents": 4,
            },
        },
    },
    "local-multi": {
        "description": "Multiple local models on different GPUs (vLLM multi-model)",
        "detail": "Run different model sizes for different task complexities. 7B for fast tasks, 70B for complex ones.",
        "config": {
            "database": {"path": "./kaos.db", "wal_mode": True, "compression": "zstd"},
            "models": {
                "small": {
                    "provider": "local",
                    "endpoint": "http://localhost:8000/v1",
                    "max_context": 32768,
                    "use_for": ["trivial", "code_completion"],
                },
                "large": {
                    "provider": "local",
                    "endpoint": "http://localhost:8001/v1",
                    "max_context": 131072,
                    "use_for": ["moderate", "complex", "critical", "planning"],
                },
            },
            "router": {
                "classifier_model": "small",
                "fallback_model": "large",
                "context_compression": True,
            },
            "ccr": {
                "max_iterations": 100,
                "checkpoint_interval": 10,
                "max_parallel_agents": 8,
            },
        },
    },
    "anthropic": {
        "description": "Use Anthropic Claude API (requires API key)",
        "detail": "Send tasks to Claude via the Anthropic API. Set ANTHROPIC_API_KEY environment variable.",
        "config": {
            "database": {"path": "./kaos.db", "wal_mode": True, "compression": "zstd"},
            "models": {
                "claude-sonnet": {
                    "provider": "anthropic",
                    "model_id": "claude-sonnet-4-20250514",
                    "api_key_env": "ANTHROPIC_API_KEY",
                    "max_context": 200000,
                    "use_for": ["trivial", "moderate", "complex", "critical"],
                },
            },
            "router": {
                "fallback_model": "claude-sonnet",
                "context_compression": True,
            },
            "ccr": {
                "max_iterations": 100,
                "checkpoint_interval": 10,
                "max_parallel_agents": 4,
            },
        },
    },
    "openai": {
        "description": "Use OpenAI API (requires API key)",
        "detail": "Send tasks to GPT-4o via the OpenAI API. Set OPENAI_API_KEY environment variable.",
        "config": {
            "database": {"path": "./kaos.db", "wal_mode": True, "compression": "zstd"},
            "models": {
                "gpt-4o": {
                    "provider": "openai",
                    "model_id": "gpt-4o",
                    "api_key_env": "OPENAI_API_KEY",
                    "max_context": 128000,
                    "use_for": ["trivial", "moderate", "complex", "critical"],
                },
            },
            "router": {
                "fallback_model": "gpt-4o",
                "context_compression": True,
            },
            "ccr": {
                "max_iterations": 100,
                "checkpoint_interval": 10,
                "max_parallel_agents": 4,
            },
        },
    },
    "hybrid": {
        "description": "Mix local + cloud models (best of both worlds)",
        "detail": "Route trivial tasks to a free local model, complex tasks to a powerful cloud model. Saves money without sacrificing quality.",
        "config": {
            "database": {"path": "./kaos.db", "wal_mode": True, "compression": "zstd"},
            "models": {
                "local-fast": {
                    "provider": "local",
                    "endpoint": "http://localhost:8000/v1",
                    "max_context": 32768,
                    "use_for": ["trivial", "code_completion"],
                },
                "claude-powerful": {
                    "provider": "anthropic",
                    "model_id": "claude-sonnet-4-20250514",
                    "api_key_env": "ANTHROPIC_API_KEY",
                    "max_context": 200000,
                    "use_for": ["complex", "critical", "planning"],
                },
            },
            "router": {
                "classifier_model": "local-fast",
                "fallback_model": "claude-powerful",
                "context_compression": True,
            },
            "ccr": {
                "max_iterations": 100,
                "checkpoint_interval": 10,
                "max_parallel_agents": 8,
            },
        },
    },
}


def run_setup(output_path: str = "./kaos.yaml"):
    """Run the interactive setup wizard."""

    console.print(Panel(
        "[bold bright_white]KAOS Setup Wizard[/]\n\n"
        "This will create a [cyan]kaos.yaml[/] configuration file for your project.\n"
        "Answer a few questions and you'll be ready to go.",
        border_style="bright_blue",
    ))

    # Step 1: Choose setup type
    console.print("\n[bold]How do you want to use KAOS?[/]\n")
    choices = list(PRESETS.keys())
    for i, key in enumerate(choices, 1):
        preset = PRESETS[key]
        console.print(f"  [cyan]{i}[/]) [bold]{preset['description']}[/]")
        console.print(f"     [dim]{preset['detail']}[/]")
        console.print()

    choice_num = Prompt.ask(
        "Choose a setup",
        choices=[str(i) for i in range(1, len(choices) + 1)],
        default="1",
    )
    selected = choices[int(choice_num) - 1]
    preset = PRESETS[selected]
    config = dict(preset["config"])

    console.print(f"\n[green]Selected:[/] {preset['description']}\n")

    # Step 2: Customize based on selection
    if selected == "claude-code":
        console.print("[dim]No LLM configuration needed — Claude Code handles everything.[/]")

    elif selected in ("local", "local-multi"):
        endpoint = Prompt.ask(
            "Local model endpoint",
            default="http://localhost:8000/v1",
        )
        if selected == "local":
            config["models"]["local-model"]["endpoint"] = endpoint
        else:
            config["models"]["small"]["endpoint"] = endpoint
            endpoint2 = Prompt.ask(
                "Second model endpoint (for complex tasks)",
                default="http://localhost:8001/v1",
            )
            config["models"]["large"]["endpoint"] = endpoint2

    elif selected == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            console.print("[yellow]ANTHROPIC_API_KEY not set in environment.[/]")
            console.print("[dim]Set it with: export ANTHROPIC_API_KEY=your-key-here[/]")

        model = Prompt.ask(
            "Claude model",
            default="claude-sonnet-4-20250514",
        )
        config["models"]["claude-sonnet"]["model_id"] = model

    elif selected == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            console.print("[yellow]OPENAI_API_KEY not set in environment.[/]")
            console.print("[dim]Set it with: export OPENAI_API_KEY=your-key-here[/]")

        model = Prompt.ask("OpenAI model", default="gpt-4o")
        config["models"]["gpt-4o"]["model_id"] = model

    elif selected == "hybrid":
        endpoint = Prompt.ask(
            "Local model endpoint (for fast/cheap tasks)",
            default="http://localhost:8000/v1",
        )
        config["models"]["local-fast"]["endpoint"] = endpoint

        cloud = Prompt.ask(
            "Cloud provider for complex tasks",
            choices=["anthropic", "openai"],
            default="anthropic",
        )
        if cloud == "openai":
            config["models"]["cloud-powerful"] = config["models"].pop("claude-powerful")
            config["models"]["cloud-powerful"]["provider"] = "openai"
            config["models"]["cloud-powerful"]["model_id"] = "gpt-4o"
            config["models"]["cloud-powerful"]["api_key_env"] = "OPENAI_API_KEY"
            config["models"]["cloud-powerful"]["max_context"] = 128000
            config["router"]["fallback_model"] = "cloud-powerful"

    # Step 3: Confirm and write
    console.print()
    console.print(Panel(
        yaml.dump(config, default_flow_style=False, sort_keys=False),
        title="kaos.yaml",
        border_style="green",
    ))

    if Path(output_path).exists():
        overwrite = Confirm.ask(f"[yellow]{output_path} already exists. Overwrite?[/]", default=False)
        if not overwrite:
            console.print("[dim]Setup cancelled.[/]")
            return

    with open(output_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    console.print(f"\n[green]Config written to {output_path}[/]")

    # Auto-init the database
    from kaos.core import Kaos
    db_path = config.get("database", {}).get("path", "./kaos.db")
    if not Path(db_path).exists():
        Kaos(db_path).close()
        console.print(f"[green]Database initialized:[/] {db_path}")
    else:
        console.print(f"[dim]Database already exists:[/] {db_path}")

    console.print()

    # ── Step 4: Install MCP server for Claude Code ───────────
    install_mcp = Confirm.ask(
        "[bold]Install KAOS as an MCP server for Claude Code?[/]",
        default=True,
    )

    if install_mcp:
        _install_mcp_server(output_path, selected)

    # ── Final: show what to do next ──────────────────────────
    console.print()
    _print_next_steps(selected, output_path, install_mcp)


def _install_mcp_server(config_path: str, preset: str) -> None:
    """Install the KAOS MCP server into Claude Code settings."""
    import json as json_mod

    project_path = str(Path.cwd().resolve()).replace("\\", "/")
    resolved_config = str(Path(config_path).resolve()).replace("\\", "/")

    # Ask where to install
    console.print()
    console.print("  [cyan]1[/]) [bold]This project only[/] (.claude/settings.json)")
    console.print("  [cyan]2[/]) [bold]All projects (global)[/] (~/.claude/settings.json)")
    scope = Prompt.ask("Install scope", choices=["1", "2"], default="1")

    if scope == "1":
        settings_dir = Path.cwd() / ".claude"
        settings_path = settings_dir / "settings.json"
        scope_label = "project"
    else:
        settings_dir = Path.home() / ".claude"
        settings_path = settings_dir / "settings.json"
        scope_label = "global"

    # Build the MCP server entry
    mcp_entry = {
        "command": "uv",
        "args": [
            "run", "--project", project_path,
            "kaos", "serve", "--transport", "stdio",
            "--config-file", resolved_config,
        ],
    }

    # Read existing settings (or start fresh)
    settings_dir.mkdir(parents=True, exist_ok=True)
    if settings_path.exists():
        try:
            existing = json_mod.loads(settings_path.read_text())
        except (json_mod.JSONDecodeError, OSError):
            existing = {}
    else:
        existing = {}

    # Merge — don't overwrite other settings or MCP servers
    if "mcpServers" not in existing:
        existing["mcpServers"] = {}

    existing["mcpServers"]["kaos"] = mcp_entry

    # Write back
    settings_path.write_text(json_mod.dumps(existing, indent=2) + "\n")

    console.print(f"\n[green]MCP server installed ({scope_label}):[/] {settings_path}")
    console.print(f"[dim]KAOS will be available as 18 tools in Claude Code after restart.[/]")


def _print_next_steps(preset: str, config_path: str, mcp_installed: bool) -> None:
    """Print concrete next steps based on the chosen preset."""

    step = 1

    # Prerequisite steps (model-specific)
    if preset in ("local", "local-multi"):
        console.print(f"[bold cyan]{step}. Start your local model:[/]")
        console.print("   vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --port 8000")
        console.print()
        step += 1

    elif preset in ("anthropic", "openai"):
        env_var = "ANTHROPIC_API_KEY" if preset == "anthropic" else "OPENAI_API_KEY"
        console.print(f"[bold cyan]{step}. Set your API key:[/]")
        console.print(f"   export {env_var}=your-key-here")
        console.print()
        step += 1

    elif preset == "hybrid":
        console.print(f"[bold cyan]{step}. Start local model + set cloud API key:[/]")
        console.print("   vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --port 8000")
        console.print("   export ANTHROPIC_API_KEY=your-key-here")
        console.print()
        step += 1

    # Claude Code step
    if mcp_installed:
        console.print(f"[bold cyan]{step}. Restart Claude Code[/], then try:")
        console.print('   [italic]"Use KAOS to spawn an agent that writes hello world to /src/main.py"[/]')
    else:
        console.print(f"[bold cyan]{step}. Use the CLI:[/]")
        console.print(f"   kaos run \"your task here\" -n my-agent --config-file {config_path}")

    console.print()
    console.print("[dim]Other commands: kaos ls, kaos dashboard, kaos mh search -b text_classify[/]")
