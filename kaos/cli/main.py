"""KAOS CLI — command-line interface for the Kernel for Agent Orchestration & Sandboxing."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Fix Windows cp1252 encoding crash — force UTF-8 for stdout/stderr
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from kaos import __version__ as _kaos_version
from kaos.core import Kaos

console = Console()

DEFAULT_DB = os.environ.get("KAOS_DB", "./kaos.db")
DEFAULT_CONFIG = os.environ.get("KAOS_CONFIG", "./kaos.yaml")


def _get_afs(db: str) -> Kaos:
    """Get or create an Kaos instance."""
    return Kaos(db_path=db)


def _json_out(ctx, data):
    """Output data as JSON if --json is set, otherwise return False."""
    if ctx.obj.get("json"):
        click.echo(json.dumps(data, indent=2, default=str))
        return True
    return False


def _json_err(ctx, msg: str):
    """Output error as JSON if --json is set, otherwise return False."""
    if ctx.obj.get("json"):
        click.echo(json.dumps({"error": msg}))
        ctx.exit(1)
        return True
    return False


@click.group()
@click.version_option(version=_kaos_version, prog_name="kaos")
@click.option("--json", "json_output", is_flag=True, default=False,
              help="Output structured JSON (auto-enabled when piped)")
@click.pass_context
def cli(ctx, json_output):
    """KAOS — Kernel for Agent Orchestration & Sandboxing.

    Every agent gets an isolated, auditable, portable virtual
    filesystem backed by SQLite. Embrace the KAOS.
    """
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_output or not sys.stdout.isatty()


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def init(db: str):
    """Initialize a new Kaos database."""
    if Path(db).exists():
        console.print(f"[yellow]Database already exists:[/yellow] {db}")
        return

    afs = _get_afs(db)
    afs.close()
    console.print(f"[green]Initialized KAOS database:[/green] {db}")


@cli.command()
@click.option("-o", "--output", default="./kaos.yaml", help="Output config file path")
def setup(output: str):
    """Interactive setup wizard — configure KAOS for your project."""
    from kaos.cli.setup import run_setup
    run_setup(output_path=output)


@cli.group("doctor")
def doctor_group():
    """Smoke-test infrastructure (providers, proposer, etc.)."""


@doctor_group.command("proposer")
@click.option("--config-file", default=DEFAULT_CONFIG,
              help="Config file path")
@click.option("--wall-timeout", default=30.0, type=float,
              help="Hard wall timeout per provider (seconds)")
@click.option("--idle-timeout", default=10.0, type=float,
              help="Idle (no-new-bytes) timeout per provider (seconds)")
@click.pass_context
def doctor_proposer(ctx, config_file: str, wall_timeout: float,
                    idle_timeout: float):
    """Send a tiny prompt to every configured provider and report
    latency + stream health. Catches the P0 #11 failure mode early.

    Exits non-zero if ANY provider fails to respond within the bounds.
    """
    import asyncio
    import time as _time
    from kaos.router.providers import ProposerStalled

    if not Path(config_file).exists():
        msg = f"Config not found: {config_file}"
        if _json_err(ctx, msg):
            return
        console.print(f"[red]{msg}[/red]")
        ctx.exit(1)
        return

    from kaos.router.gepa import GEPARouter
    router = GEPARouter.from_config(config_file)

    async def _smoke_one(name: str):
        client = router.clients.get(name)
        if client is None:
            return {"model": name, "status": "no-client", "ms": None,
                    "detail": "no LLMProvider/VLLMClient resolved"}
        # Override provider-level timeouts where supported so the smoke
        # check fails fast rather than inheriting the production wall.
        for attr, val in (("timeout", wall_timeout),
                          ("idle_timeout", idle_timeout)):
            if hasattr(client, attr):
                try:
                    setattr(client, attr, val)
                except Exception:
                    pass
        prompt = "Reply with the single word: OK"
        msgs = [{"role": "user", "content": prompt}]
        model_id = router.models[name].model_id or name
        t0 = _time.perf_counter()
        try:
            r = await client.chat(model=model_id, messages=msgs,
                                  temperature=0.0, max_tokens=8)
            ms = (_time.perf_counter() - t0) * 1000
            text = ""
            try:
                text = (r.choices[0].message.content or "").strip()
            except Exception:
                pass
            return {"model": name, "status": "ok", "ms": round(ms, 1),
                    "detail": text[:60]}
        except ProposerStalled as e:
            ms = (_time.perf_counter() - t0) * 1000
            return {"model": name, "status": "stalled",
                    "ms": round(ms, 1), "detail": str(e)}
        except TimeoutError as e:
            ms = (_time.perf_counter() - t0) * 1000
            return {"model": name, "status": "wall-timeout",
                    "ms": round(ms, 1), "detail": str(e)}
        except Exception as e:
            ms = (_time.perf_counter() - t0) * 1000
            return {"model": name, "status": "error",
                    "ms": round(ms, 1), "detail": f"{type(e).__name__}: {e}"}

    async def _smoke_all():
        return await asyncio.gather(*[_smoke_one(n) for n in router.models])

    rows = asyncio.run(_smoke_all())
    bad = [r for r in rows if r["status"] != "ok"]

    if _json_out(ctx, {"results": rows,
                       "failed": [r["model"] for r in bad]}):
        return

    console.print(f"[bold]Proposer smoke — {len(rows)} provider(s)[/bold] "
                  f"(wall={wall_timeout}s, idle={idle_timeout}s)")
    for r in rows:
        c = {"ok": "green", "stalled": "yellow",
             "wall-timeout": "red", "error": "red",
             "no-client": "yellow"}.get(r["status"], "white")
        ms = f"{r['ms']:.1f} ms" if r["ms"] is not None else "—"
        console.print(f"  [{c}]{r['status']:13}[/{c}] {r['model']:24} "
                      f"{ms:>10}   [dim]{r['detail']}[/dim]")
    if bad:
        ctx.exit(1)


@cli.group("eval")
def eval_group():
    """Falsifiable-eval primitive (kaos.eval.harness)."""


@eval_group.command("verify-numerics")
@click.argument("artifact", type=click.Path(exists=True))
@click.option("--db", default=DEFAULT_DB, help="kaos.db path (measurement corpus)")
@click.option("--results", multiple=True,
              help="results.json path(s) to add to the corpus (repeatable)")
@click.pass_context
def eval_verify_numerics(ctx, artifact: str, db: str, results: tuple[str, ...]):
    """Trace every measurement-shaped number in ARTIFACT to a recorded measurement.

    Numbers that resolve to the experiments journal or a given results.json are
    'verified'; measurement-shaped numbers with no trace are 'unverifiable' and
    listed. Semver, dates, years, file:line refs, URLs, hashes and #-ordinals are
    allowlisted. Exits non-zero if any number is unverifiable (CI-gate friendly).
    """
    from kaos.eval.verify_numerics import verify_text

    text = Path(artifact).read_text(encoding="utf-8")
    report = verify_text(text, db_path=db, results_paths=list(results))

    if _json_out(ctx, report.to_dict()):
        ctx.exit(0 if report.ok else 1)
        return

    console.print(
        f"[bold]{artifact}[/bold] — {len(report.verified)} verified, "
        f"[{'green' if report.ok else 'red'}]{len(report.unverifiable)} unverifiable[/] "
        f"(corpus: {report.corpus_size} recorded numbers)"
    )
    for c in report.unverifiable:
        console.print(f"  [red]✗[/red] {c.raw}  [dim]…{c.context}…[/dim]")
    if not report.ok:
        ctx.exit(1)


@eval_group.group("probe")
def eval_probe_group():
    """Run / verify / falsify a Probe subclass."""


def _load_probe_class(spec: str):
    """spec = ``pkg.module:ClassName``."""
    import importlib
    if ":" not in spec:
        raise click.UsageError(
            f"--probe must be 'pkg.module:ClassName', got {spec!r}"
        )
    mod_name, cls_name = spec.split(":", 1)
    from kaos.plugins import ensure_probe_paths
    ensure_probe_paths()
    mod = importlib.import_module(mod_name)
    try:
        return getattr(mod, cls_name)
    except AttributeError as e:
        raise click.UsageError(
            f"module {mod_name!r} has no attribute {cls_name!r}"
        ) from e


@eval_probe_group.command("run")
@click.option("--probe", "probe_spec", required=True,
              help="Probe class as 'pkg.module:ClassName'")
@click.option("--out-dir", required=True,
              help="Directory to write results.json + per-arm artefacts")
@click.pass_context
def eval_probe_run(ctx, probe_spec: str, out_dir: str):
    """Execute the probe end-to-end. Writes results.json with the
    binding verdict. Exits non-zero on REJECT/VOID."""
    cls = _load_probe_class(probe_spec)
    probe = cls()
    result = probe.run(out_dir=out_dir)
    verdict = result.get("verdict", "?")

    if _json_out(ctx, {"probe": probe_spec, "out_dir": out_dir,
                       "verdict": verdict,
                       "judge_kappa": result.get("judge_kappa"),
                       "gates": result.get("gates", [])}):
        if not verdict.startswith("ACCEPT"):
            ctx.exit(1)
        return

    console.print(f"[bold]Probe[/bold]: {probe_spec}")
    console.print(f"[bold]Verdict[/bold]: {verdict}")
    if not verdict.startswith("ACCEPT"):
        ctx.exit(1)


@eval_probe_group.command("verify")
@click.option("--probe", "probe_spec", required=True,
              help="Probe class as 'pkg.module:ClassName'")
@click.option("--results", "results_path", required=True,
              help="Path to results.json produced by 'probe run'")
@click.pass_context
def eval_probe_verify(ctx, probe_spec: str, results_path: str):
    """Re-compute the verdict from a saved results.json. Confirms
    the on-disk verdict matches the gate code at HEAD."""
    cls = _load_probe_class(probe_spec)
    probe = cls()
    verdict = probe.verify(results_path)

    if _json_out(ctx, {"probe": probe_spec, "results": results_path,
                       "verdict": verdict}):
        if not verdict.startswith("ACCEPT"):
            ctx.exit(1)
        return

    console.print(f"[bold]Verify[/bold]: {results_path}")
    console.print(f"[bold]Verdict[/bold]: {verdict}")
    if not verdict.startswith("ACCEPT"):
        ctx.exit(1)


@eval_probe_group.command("falsify")
@click.option("--probe", "probe_spec", required=True,
              help="Probe class as 'pkg.module:ClassName'")
@click.pass_context
def eval_probe_falsify(ctx, probe_spec: str):
    """Gate-first self-test: substitute the feature arm by a baseline
    and prove a kill-gate fires. A harness that cannot lose is
    INADMISSIBLE; exits non-zero in that case."""
    cls = _load_probe_class(probe_spec)
    probe = cls()
    outcomes, verdict = probe.falsify()
    admissible = verdict.startswith("REJECT")

    if _json_out(ctx, {"probe": probe_spec, "verdict": verdict,
                       "admissible": admissible,
                       "outcomes": [
                           {"gate": o.gate, "name": o.name,
                            "passed": o.passed, "kill": o.kill,
                            "detail": o.detail}
                           for o in outcomes
                       ]}):
        if not admissible:
            ctx.exit(1)
        return

    console.print(f"[bold]Falsify[/bold]: {probe_spec}")
    for o in outcomes:
        flag = "PASS" if o.passed else ("FAIL-KILL" if o.kill else "FAIL")
        c = "green" if o.passed else ("red" if o.kill else "yellow")
        console.print(f"  [{c}][{flag:9}][/{c}] {o.gate}  {o.name}")
        if o.detail:
            console.print(f"             [dim]{o.detail}[/dim]")
    console.print(f"[bold]Verdict[/bold]: {verdict}")
    if not admissible:
        console.print("[red]BROKEN HARNESS — feature cannot lose. "
                      "Inadmissible per gate-first invariant.[/red]")
        ctx.exit(1)
    else:
        console.print("[green]Harness is ADMISSIBLE.[/green]")


@cli.group("experiment")
def experiment_group():
    """Append-only journal of probe / mh_search / benchmark runs."""


@experiment_group.command("log")
@click.option("--name", required=True, help="Free label (e.g. probe name)")
@click.option("--family", default=None,
              help="probe | mh_search | benchmark | ...")
@click.option("--verdict", default=None,
              help="ACCEPT | REJECT: ... | VOID: ...")
@click.option("--judge-kappa", default=None, type=float)
@click.option("--lock-sha256", default=None)
@click.option("--git-sha", default=None,
              help="HEAD sha; empty string suppresses auto-fill")
@click.option("--arms-json", default=None,
              help="Path to JSON file with per-arm aggregates")
@click.option("--gates-json", default=None,
              help="Path to JSON file with list of gate outcomes")
@click.option("--metadata-json", default=None,
              help="Path to JSON file with caller-defined metadata")
@click.option("--results-path", default=None,
              help="On-disk results.json (recorded as a pointer)")
@click.option("--db", default=DEFAULT_DB, help="kaos.db path")
@click.pass_context
def experiment_log(ctx, name: str, family: str | None,
                   verdict: str | None, judge_kappa: float | None,
                   lock_sha256: str | None, git_sha: str | None,
                   arms_json: str | None, gates_json: str | None,
                   metadata_json: str | None, results_path: str | None,
                   db: str):
    """Insert one experiment row. Echoes the new exp_id."""
    from kaos.experiments import ExperimentStore

    def _load_json(path: str | None, default):
        if not path:
            return default
        return json.loads(Path(path).read_text())

    with ExperimentStore(db) as store:
        exp_id = store.log_run(
            name=name, family=family, verdict=verdict,
            judge_kappa=judge_kappa, lock_sha256=lock_sha256,
            git_sha=git_sha,
            arms=_load_json(arms_json, {}),
            gates=_load_json(gates_json, []),
            metadata=_load_json(metadata_json, {}),
            results_path=results_path,
        )

    if _json_out(ctx, {"exp_id": exp_id, "name": name}):
        return
    console.print(f"[green]exp_id={exp_id}[/green]  {name}")


@experiment_group.command("list")
@click.option("--name", default=None)
@click.option("--family", default=None)
@click.option("--verdict-prefix", default=None,
              help="Filter to verdicts starting with this prefix "
                   "(e.g. REJECT)")
@click.option("--limit", default=50, type=int)
@click.option("--db", default=DEFAULT_DB, help="kaos.db path")
@click.pass_context
def experiment_list(ctx, name: str | None, family: str | None,
                    verdict_prefix: str | None, limit: int, db: str):
    """List recent experiments, newest first."""
    from kaos.experiments import ExperimentStore

    with ExperimentStore(db) as store:
        rows = store.list(name=name, family=family,
                          verdict_prefix=verdict_prefix, limit=limit)

    if _json_out(ctx, {"experiments": [
        {"exp_id": r.exp_id, "name": r.name, "family": r.family,
         "git_sha": r.git_sha, "lock_sha256": r.lock_sha256,
         "started_at": r.started_at, "verdict": r.verdict,
         "judge_kappa": r.judge_kappa}
        for r in rows
    ]}):
        return

    console.print(f"[bold]{len(rows)} experiment(s)[/bold]")
    for r in rows:
        v = r.verdict or "—"
        vc = ("green" if v.startswith("ACCEPT")
              else "red" if v.startswith("REJECT")
              else "yellow" if v.startswith("VOID")
              else "white")
        sha = (r.git_sha or "—")[:8]
        console.print(
            f"  [{vc}]#{r.exp_id:<5}[/{vc}] {r.started_at}  "
            f"{r.name:30}  [{vc}]{v[:40]}[/{vc}]  {sha}"
        )


@experiment_group.command("show")
@click.argument("exp_id", type=int)
@click.option("--db", default=DEFAULT_DB, help="kaos.db path")
@click.pass_context
def experiment_show(ctx, exp_id: int, db: str):
    """Dump one experiment row."""
    from dataclasses import asdict

    from kaos.experiments import ExperimentStore

    with ExperimentStore(db) as store:
        exp = store.get(exp_id)
    if exp is None:
        if _json_err(ctx, f"no experiment #{exp_id}"):
            return
        console.print(f"[red]no experiment #{exp_id}[/red]")
        ctx.exit(1)
        return

    if _json_out(ctx, asdict(exp)):
        return
    console.print(json.dumps(asdict(exp), indent=2))


@experiment_group.command("compare")
@click.argument("a_id", type=int)
@click.argument("b_id", type=int)
@click.option("--db", default=DEFAULT_DB, help="kaos.db path")
@click.pass_context
def experiment_compare(ctx, a_id: int, b_id: int, db: str):
    """Diff two experiment rows by field. Useful for 'what changed
    since the last run?'."""
    from kaos.experiments import ExperimentStore

    with ExperimentStore(db) as store:
        try:
            diff = store.compare(a_id, b_id)
        except ValueError as e:
            if _json_err(ctx, str(e)):
                return
            console.print(f"[red]{e}[/red]")
            ctx.exit(1)
            return

    if _json_out(ctx, diff):
        return
    console.print(f"[bold]compare #{a_id} vs #{b_id}[/bold]")
    if not diff["changes"]:
        console.print("[green]no changes[/green]")
        return
    for k, (va, vb) in diff["changes"].items():
        console.print(f"  [yellow]{k}[/yellow]: {va!r}  ->  {vb!r}")


@cli.command()
@click.argument("task")
@click.option("--name", "-n", required=True, help="Agent name")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="Config file path")
@click.option("--model", "-m", help="Force a specific model")
@click.option("--checkpoint-interval", default=10, help="Auto-checkpoint every N iterations")
@click.option("--ask/--no-ask", default=False,
              help="Run the intake step first: analyze the task and ask any clarifying "
                   "questions the builder genuinely needs before starting (0 or more — dynamic, "
                   "no fixed count).")
@click.option("--answers", type=click.Path(exists=True, dir_okay=False),
              help="Path to a JSON file with pre-filled answers (for non-interactive --ask).")
@click.option("--intake-only", is_flag=True, default=False,
              help="Run only the intake step and print the questions as JSON. Does not spawn "
                   "an agent. Useful for scripting or previewing.")
def run(task: str, name: str, db: str, config_file: str, model: str,
        checkpoint_interval: int, ask: bool, answers: str, intake_only: bool):
    """Spawn and run an agent with a task."""
    from kaos.router.gepa import GEPARouter
    from kaos.ccr.runner import ClaudeCodeRunner

    afs = _get_afs(db)

    if not Path(config_file).exists():
        console.print(f"[red]Config file not found:[/red] {config_file}")
        console.print("Run: cp kaos.yaml.example kaos.yaml")
        return

    router = GEPARouter.from_config(config_file)

    # ── Intake step (dynamic clarifying questions) ──────────────────
    if ask or intake_only:
        from kaos.intake import analyze, ask_interactively, enrich_task

        try:
            questions = asyncio.run(analyze(task, router, force_model=model))
        except Exception as e:
            console.print(f"[red]Intake step failed:[/red] {e}")
            afs.close()
            return

        if intake_only:
            click.echo(json.dumps([q.to_dict() for q in questions], indent=2))
            afs.close()
            return

        if not questions:
            console.print("[green]\u2714 intake-agent:[/green] task is fully specified. "
                          "No questions — proceeding.")
        else:
            if answers:
                with open(answers) as f:
                    answer_map = json.load(f)
            else:
                answer_map = ask_interactively(questions)
            task = enrich_task(task, answer_map)

    ccr = ClaudeCodeRunner(
        afs, router, checkpoint_interval=checkpoint_interval
    )

    agent_config = {}
    if model:
        agent_config["force_model"] = model

    agent_id = afs.spawn(name=name, config=agent_config)
    console.print(f"[cyan]Spawned agent:[/cyan] {agent_id} ({name})")

    exit_code = 0
    try:
        result = asyncio.run(ccr.run_agent(agent_id, task))
        status = {a["agent_id"]: a["status"] for a in afs.list_agents()}.get(agent_id)
        if status in ("failed", "killed"):
            # The runner returns a string even on max-iterations/timeout
            # failure paths — the agent's STATUS is the truth, and the exit
            # code must tell it (fleet launchers trust exit codes).
            console.print(f"\n[red]Agent {status}:[/red]\n{result}")
            exit_code = 1
        else:
            console.print(f"\n[green]Result:[/green]\n{result}")
    except Exception as e:
        console.print(f"\n[red]Agent failed:[/red] {e}")
        exit_code = 1
    finally:
        afs.close()
    if exit_code:
        raise SystemExit(exit_code)


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="Config file path")
@click.option(
    "--task", "-t", multiple=True, nargs=2, metavar="NAME PROMPT",
    help="Task as --task NAME PROMPT (can specify multiple)"
)
def parallel(db: str, config_file: str, task: tuple):
    """Run multiple agents in parallel."""
    from kaos.router.gepa import GEPARouter
    from kaos.ccr.runner import ClaudeCodeRunner

    if not task:
        console.print("[red]No tasks specified. Use --task NAME PROMPT[/red]")
        return

    afs = _get_afs(db)
    router = GEPARouter.from_config(config_file)
    ccr = ClaudeCodeRunner(afs, router)

    tasks = [{"name": t[0], "prompt": t[1]} for t in task]

    console.print(f"[cyan]Running {len(tasks)} agents in parallel...[/cyan]")
    outcomes = asyncio.run(ccr.run_parallel_detailed(tasks))

    failed = [o for o in outcomes if not o["ok"]]
    for o in outcomes:
        mark = "[green]ok[/green]" if o["ok"] else f"[red]{o['status']}[/red]"
        console.print(f"\n[bold]Agent {o['name']}[/bold] ({mark}):")
        console.print(str(o["result"])[:500])
    afs.close()
    if failed:
        console.print(f"\n[red]{len(failed)}/{len(outcomes)} agent(s) failed[/red]")
        raise SystemExit(1)


@cli.command("ls")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--status", "-s", help="Filter by status")
@click.pass_context
def list_agents(ctx, db: str, status: str):
    """List all agents."""
    afs = _get_afs(db)
    agents = afs.list_agents(status_filter=status)

    if _json_out(ctx, agents):
        afs.close()
        return

    if not agents:
        console.print("[dim]No agents found[/dim]")
        return

    table = Table(title="Agents")
    table.add_column("ID", style="cyan", max_width=14)
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Created")

    for agent in agents:
        status_text = Text(agent["status"])
        if agent["status"] == "running":
            status_text.stylize("bold green")
        elif agent["status"] == "completed":
            status_text.stylize("green")
        elif agent["status"] in ("failed", "killed"):
            status_text.stylize("red")

        table.add_row(
            agent["agent_id"][:12] + "...",
            agent["name"],
            status_text,
            agent["created_at"][:19] if agent["created_at"] else "",
        )

    console.print(table)
    afs.close()


@cli.command()
@click.argument("sql")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def query(ctx, sql: str, db: str):
    """Run a read-only SQL query against the agent database."""
    afs = _get_afs(db)
    try:
        results = afs.query(sql)
        if _json_out(ctx, results):
            return
        if results:
            table = Table()
            for col in results[0].keys():
                table.add_column(col)
            for row in results:
                table.add_row(*[str(v)[:80] for v in row.values()])
            console.print(table)
        else:
            console.print("[dim]No results[/dim]")
    except PermissionError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    except Exception as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]Query error: {e}[/red]")
    finally:
        afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--label", "-l", help="Optional checkpoint label")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def checkpoint(ctx, agent_id: str, label: str, db: str):
    """Create a checkpoint for an agent."""
    afs = _get_afs(db)
    try:
        cp_id = afs.checkpoint(agent_id, label=label)
        if _json_out(ctx, {"checkpoint_id": cp_id, "agent_id": agent_id, "label": label}):
            return
        console.print(f"[green]Checkpoint created:[/green] {cp_id}")
        if label:
            console.print(f"  Label: {label}")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--checkpoint", "checkpoint_id", required=True, help="Checkpoint ID to restore")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def restore(agent_id: str, checkpoint_id: str, db: str):
    """Restore an agent to a previous checkpoint."""
    afs = _get_afs(db)
    try:
        afs.restore(agent_id, checkpoint_id)
        console.print(f"[green]Agent {agent_id} restored to checkpoint {checkpoint_id}[/green]")
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--from", "from_cp", required=True, help="Source checkpoint ID")
@click.option("--to", "to_cp", required=True, help="Target checkpoint ID")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def diff(agent_id: str, from_cp: str, to_cp: str, db: str):
    """Compare two checkpoints of an agent."""
    from kaos.cli.diff import render_diff

    afs = _get_afs(db)
    try:
        result = afs.diff_checkpoints(agent_id, from_cp, to_cp)
        render_diff(result, console)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def checkpoints(ctx, agent_id: str, db: str):
    """List all checkpoints for an agent."""
    afs = _get_afs(db)
    cps = afs.list_checkpoints(agent_id)

    if _json_out(ctx, cps):
        afs.close()
        return

    if not cps:
        console.print("[dim]No checkpoints found[/dim]")
        return

    table = Table(title=f"Checkpoints for {agent_id[:12]}...")
    table.add_column("ID", style="cyan", max_width=14)
    table.add_column("Label")
    table.add_column("Created")
    table.add_column("Event ID", justify="right")

    for cp in cps:
        table.add_row(
            cp["checkpoint_id"][:12] + "...",
            cp.get("label") or "-",
            cp["created_at"][:19],
            str(cp.get("event_id") or "-"),
        )

    console.print(table)
    afs.close()


@cli.command("export")
@click.argument("agent_id")
@click.option("-o", "--output", required=True, help="Output file path")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def export_agent(agent_id: str, output: str, db: str):
    """Export an agent to a standalone database file."""
    import shutil
    import sqlite3

    afs = _get_afs(db)

    # Verify agent exists
    try:
        afs.status(agent_id)
    except ValueError:
        console.print(f"[red]Agent not found: {agent_id}[/red]")
        return

    # Create a new database with just this agent's data
    shutil.copy2(db, output)

    # Remove other agents from the copy
    export_conn = sqlite3.connect(output)
    other_agents = export_conn.execute(
        "SELECT agent_id FROM agents WHERE agent_id != ?", (agent_id,)
    ).fetchall()

    for (other_id,) in other_agents:
        for table in ("files", "tool_calls", "state", "events", "checkpoints"):
            export_conn.execute(f"DELETE FROM {table} WHERE agent_id = ?", (other_id,))
        export_conn.execute("DELETE FROM agents WHERE agent_id = ?", (other_id,))

    # Clean up orphaned blobs
    export_conn.execute(
        "DELETE FROM blobs WHERE content_hash NOT IN (SELECT content_hash FROM files WHERE content_hash IS NOT NULL)"
    )
    export_conn.execute("VACUUM")
    export_conn.commit()
    export_conn.close()

    console.print(f"[green]Exported agent {agent_id[:12]}... to {output}[/green]")
    afs.close()


@cli.command("import")
@click.argument("file_path")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--merge/--replace", default=True, help="Merge or replace existing data")
def import_agent(file_path: str, db: str, merge: bool):
    """Import an agent from a standalone database file."""
    import sqlite3

    if not Path(file_path).exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        return

    afs = _get_afs(db)
    source = sqlite3.connect(file_path)

    agents = source.execute("SELECT agent_id, name FROM agents").fetchall()
    for agent_id, name in agents:
        console.print(f"[cyan]Importing agent:[/cyan] {agent_id[:12]}... ({name})")

    # Attach source database
    afs.conn.execute(f"ATTACH DATABASE '{file_path}' AS import_db")

    try:
        for table in ("agents", "blobs", "files", "tool_calls", "state", "events", "checkpoints"):
            afs.conn.execute(f"INSERT OR IGNORE INTO {table} SELECT * FROM import_db.{table}")
        afs.conn.commit()
        console.print(f"[green]Import complete — {len(agents)} agent(s) imported[/green]")
    except Exception as e:
        console.print(f"[red]Import failed: {e}[/red]")
    finally:
        afs.conn.execute("DETACH DATABASE import_db")
        source.close()
        afs.close()


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--port", default=3100, help="MCP server port")
@click.option("--host", default="127.0.0.1", help="MCP server host")
@click.option("--transport", default="stdio", type=click.Choice(["stdio", "sse"]), help="Transport")
@click.option("--config-file", default=DEFAULT_CONFIG, help="Config file path")
def serve(db: str, port: int, host: str, transport: str, config_file: str):
    """Start the Kaos MCP server."""
    from kaos.mcp.server import init_server
    from kaos.router.gepa import GEPARouter
    from kaos.ccr.runner import ClaudeCodeRunner

    afs = _get_afs(db)

    # Try config file first, then fall back to claude_code provider (no API key needed)
    _cfg_paths = [config_file, os.environ.get("KAOS_CONFIG", ""), "./kaos.yaml"]
    _loaded = False
    for _cfg in _cfg_paths:
        if _cfg and Path(_cfg).exists():
            router = GEPARouter.from_config(_cfg)
            _loaded = True
            break

    if not _loaded:
        # Default: use claude_code provider (Claude Code subscription, no API key)
        from kaos.router.gepa import ModelConfig
        from kaos.router.providers import ClaudeCodeProvider
        _provider = ClaudeCodeProvider(model_id="claude-sonnet-4-6")
        from kaos.router.gepa import GEPARouter as _GR
        router = _GR(
            models={"claude-sonnet": ModelConfig(
                name="claude-sonnet",
                provider="claude_code",
                model_id="claude-sonnet-4-6",
                use_for=["trivial", "moderate", "complex", "critical"],
            )},
        )
        # Inject the provider directly since GEPARouter.__init__ creates it from config
        router.clients["claude-sonnet"] = _provider

    ccr = ClaudeCodeRunner(afs, router)
    mcp_server = init_server(afs, ccr)

    if transport == "stdio":
        # The MCP protocol uses stdout for JSON-RPC responses.
        # But stray print() calls and library logging also go to stdout,
        # corrupting the protocol. Fix: redirect sys.stdout to stderr
        # for all Python code, but pass the ORIGINAL stdout to
        # stdio_server so MCP responses go to the right place.
        import io
        _original_stdout = sys.stdout
        sys.stdout = sys.stderr
        logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
        from mcp.server.stdio import stdio_server
        asyncio.run(_run_stdio(mcp_server, _original_stdout))
    else:
        console.print(f"[cyan]Listening on {host}:{port}[/cyan]")
        from mcp.server.sse import SseServerTransport
        asyncio.run(_run_sse(mcp_server, host, port))


async def _run_stdio(mcp_server, original_stdout=None):
    from mcp.server.stdio import stdio_server
    # If we redirected sys.stdout, temporarily restore it so
    # stdio_server() binds to the real stdout file descriptor.
    if original_stdout:
        saved = sys.stdout
        sys.stdout = original_stdout
    async with stdio_server() as (read, write):
        if original_stdout:
            sys.stdout = saved  # re-redirect after binding
        await mcp_server.run(read, write, mcp_server.create_initialization_options())


async def _run_sse(mcp_server, host: str, port: int):
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route
    import uvicorn

    sse = SseServerTransport("/messages")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await mcp_server.run(
                streams[0], streams[1], mcp_server.create_initialization_options()
            )

    app = Starlette(routes=[
        Route("/sse", endpoint=handle_sse),
        Route("/messages", endpoint=sse.handle_post_message, methods=["POST"]),
    ])

    config = uvicorn.Config(app, host=host, port=port)
    server = uvicorn.Server(config)
    await server.serve()


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def dashboard(db: str):
    """Launch the TUI dashboard for real-time agent monitoring."""
    from kaos.cli.dashboard import KaosDashboard

    afs = _get_afs(db)
    app = KaosDashboard(afs)
    app.run()
    afs.close()


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--port", default=8765, help="UI server port")
@click.option("--host", default="127.0.0.1", help="UI server host")
@click.option("--no-browser", is_flag=True, default=False, help="Don't open browser automatically")
def ui(db: str, port: int, host: str, no_browser: bool):
    """Launch the web UI dashboard (agent graph, events, tool calls)."""
    import threading
    import time as _time
    from kaos.ui.server import run as _run_ui

    db_abs = str(Path(db).resolve())

    if not no_browser:
        def _open():
            _time.sleep(1.2)
            import webbrowser
            webbrowser.open(f"http://{host}:{port}/?db={db_abs}")
        threading.Thread(target=_open, daemon=True).start()

    console.print(f"[bold cyan]KAOS UI[/bold cyan]  →  [link=http://{host}:{port}/?db={db_abs}]http://{host}:{port}/[/link]")
    console.print(f"[dim]Project: {db_abs}[/dim]")
    console.print("[dim]Ctrl+C to stop[/dim]")
    try:
        _run_ui(host=host, port=port, db=db_abs)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")


@cli.command()
@click.option("--port", default=8765, help="UI server port")
@click.option("--host", default="127.0.0.1", help="UI server host")
@click.option("--no-browser", is_flag=True, default=False, help="Don't open browser automatically")
def demo(port: int, host: str, no_browser: bool):
    """Seed a demo database and open the live dashboard.

    Creates demo.db with realistic agent data (code review swarm, parallel
    refactors, failed migrations) so you can explore the UI without running
    real agents.
    """
    import random
    import threading
    import time as _time
    from kaos.ui.server import run as _run_ui

    demo_db = str(Path("./demo.db").resolve())

    # ── Seed demo data ────────────────────────────────────────────────────
    console.print("[bold cyan]KAOS Demo[/bold cyan]  Seeding demo.db…")

    if Path(demo_db).exists():
        try:
            Path(demo_db).unlink()
        except PermissionError:
            # File locked (old server still running) — use a timestamped name
            import time as _ts
            demo_db = str(Path(f"./demo_{int(_ts.time())}.db").resolve())

    db_obj = Kaos(db_path=demo_db)

    waves = [
        {
            "goal": "Code review swarm: security + perf + style analysis of payments module",
            "agents": [
                ("security-reviewer", "completed", 4, 18,
                 "Scan payments module for SQL injection, auth bypass, and hardcoded secrets"),
                ("perf-reviewer", "completed", 3, 12,
                 "Profile payments module for N+1 queries, missing indexes, and slow loops"),
                ("style-reviewer", "completed", 3, 10,
                 "Enforce PEP 8, naming conventions, and docstring coverage"),
                ("test-writer", "completed", 5, 22,
                 "Write pytest unit tests for all payment endpoints"),
                ("doc-writer", "completed", 4, 8,
                 "Generate API reference docs from code and write usage examples"),
            ],
        },
        {
            "goal": "Parallel refactor: auth module + legacy parser + API redesign",
            "agents": [
                ("auth-refactor", "completed", 6, 28,
                 "Refactor auth.py to use JWT tokens, remove session-based auth"),
                ("legacy-parser", "failed", 2, 9,
                 "Parse legacy CSV format and migrate to Parquet — fails on encoding edge cases"),
                ("api-redesign", "running", 4, 20,
                 "Redesign REST API to follow OpenAPI 3.1 spec with versioned endpoints"),
                ("migration-agent", "running", 3, 15,
                 "Run database migration: add user_preferences table, backfill defaults"),
            ],
        },
        {
            "goal": "Post-deploy triage: investigate prod anomaly in checkout flow",
            "agents": [
                ("log-analyst", "completed", 2, 6,
                 "Parse production logs from last 2 hours, find spike in 500 errors"),
                ("runaway-agent", "killed", 1, 5,
                 "Attempt auto-rollback — terminated after exceeding 30-minute budget"),
                ("data-pipeline", "paused", 3, 11,
                 "Backfill missing orders from cache into PostgreSQL — paused awaiting approval"),
            ],
        },
    ]

    tool_names = ["fs_read", "fs_write", "fs_ls", "shell_exec", "state_set", "state_get", "fs_mkdir"]
    total_agents = 0

    for wave in waves:
        for name, target_status, num_files, num_calls, task in wave["agents"]:
            aid = db_obj.spawn(name)
            db_obj.set_state(aid, "task", task)

            db_obj.write(aid, "/src/main.py",
                         f"# {name}\n\ndef main():\n    pass\n".encode())
            db_obj.write(aid, "/README.md", f"# {name}\n\n{task}\n".encode())
            if "reviewer" in name:
                db_obj.write(aid, "/review.md",
                             f"# Review by {name}\n\n## Findings\n- Issue 1: SQL injection risk\n".encode())
            if "test" in name:
                db_obj.write(aid, "/tests/test_main.py",
                             b"import pytest\n\ndef test_basic():\n    assert True\n")
            for i in range(max(0, num_files - 2)):
                db_obj.write(aid, f"/src/module_{i}.py", f"# module {i}\n".encode())

            db_obj.set_state(aid, "progress",
                             100 if target_status == "completed" else random.randint(15, 70))
            db_obj.set_state(aid, "iteration", random.randint(5, 50))

            for i in range(num_calls):
                tool = random.choice(tool_names)
                call_id = db_obj.log_tool_call(aid, tool, {"path": f"/src/file_{i}.py"})
                db_obj.start_tool_call(call_id)
                if target_status == "failed" and i >= num_calls - 2:
                    db_obj.complete_tool_call(
                        call_id, {"error": "ConnectionError"},
                        status="error", error_message="ConnectionError",
                        token_count=random.randint(50, 300),
                    )
                else:
                    db_obj.complete_tool_call(
                        call_id, {"result": "ok"},
                        status="success", token_count=random.randint(400, 4500),
                    )

            db_obj.checkpoint(aid, label=f"{name}-initial")
            if target_status == "completed":
                db_obj.checkpoint(aid, label=f"{name}-final")
                db_obj.complete(aid)
            elif target_status == "running":
                db_obj.set_status(aid, "running", pid=12345)
                db_obj.heartbeat(aid)
            elif target_status == "failed":
                db_obj.fail(aid, error="ConnectionError: endpoint unreachable")
            elif target_status == "killed":
                db_obj.kill(aid)
            elif target_status == "paused":
                db_obj.set_status(aid, "running", pid=12345)
                db_obj.pause(aid)

            total_agents += 1

    db_obj.close()
    console.print(f"[green]✓[/green] Seeded {total_agents} agents across {len(waves)} execution waves")

    # ── Open UI ───────────────────────────────────────────────────────────
    if not no_browser:
        def _open():
            _time.sleep(1.2)
            import webbrowser
            webbrowser.open(f"http://{host}:{port}/?db={demo_db}")
        threading.Thread(target=_open, daemon=True).start()

    console.print(f"[bold cyan]Dashboard[/bold cyan]  →  [link=http://{host}:{port}/]http://{host}:{port}/[/link]")
    console.print("[dim]Ctrl+C to stop[/dim]\n")
    try:
        _run_ui(host=host, port=port, db=demo_db)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")


@cli.command()
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def kill(ctx, agent_id: str, db: str):
    """Kill a running agent."""
    afs = _get_afs(db)
    try:
        afs.kill(agent_id)
        if _json_out(ctx, {"agent_id": agent_id, "status": "killed"}):
            return
        console.print(f"[red]Agent {agent_id[:12]}... killed[/red]")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def status(ctx, agent_id: str, db: str):
    """Get detailed status of an agent."""
    afs = _get_afs(db)
    try:
        info = afs.status(agent_id)
        if _json_out(ctx, info):
            return
        console.print_json(json.dumps(info, indent=2))
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command("read")
@click.argument("agent_id")
@click.argument("path")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def read_file(ctx, agent_id: str, path: str, db: str):
    """Read a file from an agent's virtual filesystem."""
    afs = _get_afs(db)
    try:
        content = afs.read(agent_id, path)
        text = content.decode("utf-8", errors="replace")
        if ctx.obj.get("json"):
            click.echo(json.dumps({"agent_id": agent_id, "path": path, "content": text}))
        else:
            click.echo(text)
    except FileNotFoundError:
        if not _json_err(ctx, f"File not found: {agent_id}:{path}"):
            console.print(f"[red]File not found: {agent_id}:{path}[/red]")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command("logs")
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--tail", "-n", type=int, help="Show last N events")
@click.pass_context
def logs(ctx, agent_id: str, db: str, tail: int):
    """View an agent's conversation history and event log."""
    afs = _get_afs(db)
    try:
        # Try conversation first
        conversation = afs.get_state_or(agent_id, "conversation")
        events = afs.query(
            "SELECT timestamp, event_type, payload FROM events "
            "WHERE agent_id = ? ORDER BY timestamp",
            (agent_id,),
        )
        if tail:
            events = events[-tail:]

        result = {
            "agent_id": agent_id,
            "conversation_turns": len(conversation) if conversation else 0,
            "events": events,
        }
        if conversation:
            result["conversation"] = conversation

        if _json_out(ctx, result):
            return

        # Pretty print
        info = afs.status(agent_id)
        console.print(f"[bold]{info['name']}[/bold] [{info['status']}]")
        if conversation:
            console.print(f"\n[cyan]Conversation ({len(conversation)} turns):[/cyan]")
            for msg in conversation:
                role = msg.get("role", "?")
                content = str(msg.get("content", ""))[:200]
                console.print(f"  [{role}] {content}")
        console.print(f"\n[cyan]Events ({len(events)}):[/cyan]")
        for evt in events[-20:]:
            console.print(f"  {evt['timestamp'][:19]} {evt['event_type']}")
        if len(events) > 20:
            console.print(f"  ... ({len(events) - 20} more, use --json for all)")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command("index")
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def build_index(ctx, agent_id: str, db: str):
    """Build an /index.md for an agent's VFS."""
    afs = _get_afs(db)
    try:
        content = afs.build_index(agent_id)
        if ctx.obj.get("json"):
            click.echo(json.dumps({"agent_id": agent_id, "index": content}))
        else:
            console.print(content)
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command("search")
@click.argument("query_text")
@click.option("--agent", "-a", help="Scope to one agent")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--limit", "-n", default=50, help="Max results")
@click.pass_context
def search_files(ctx, query_text: str, agent: str, db: str, limit: int):
    """Full-text search across agent VFS file contents."""
    afs = _get_afs(db)
    try:
        results = afs.search(query_text, agent_id=agent, limit=limit)
        if _json_out(ctx, results):
            return
        if not results:
            console.print("[dim]No matches[/dim]")
            return
        from rich.table import Table as _T
        table = _T(title=f"Search: {query_text}")
        table.add_column("Agent", style="cyan", max_width=14)
        table.add_column("Path")
        table.add_column("Line", justify="right")
        table.add_column("Content", max_width=60)
        for r in results:
            table.add_row(r["agent_id"][:12] + "...", r["path"], str(r["line"]), r["content"][:60])
        console.print(table)
    finally:
        afs.close()


# ── Meta-Harness Commands ────────────────────────────────────────


@cli.group()
def bench():
    """Attraktor — the validated collective-learning loop (workspace brain)."""
    pass


@bench.command("status")
@click.option("--config-file", default=DEFAULT_CONFIG, help="kaos.yaml path")
@click.option("--db", default=DEFAULT_DB, help="kaos.db path")
@click.pass_context
def bench_status(ctx, config_file: str, db: str):
    """Show the Attraktor integration config + local brain contents."""
    from kaos.bench.config import load_bench_config
    from kaos.bench.schema import open_bench

    cfg = load_bench_config(config_file)
    out: dict = {
        "enabled": cfg.enabled,
        "mode": "remote" if cfg.is_remote else "local-only",
        "endpoint": cfg.endpoint,
        "workspace": cfg.workspace,
        "tier": cfg.tier,
        "publish_scope": cfg.resolved_publish_scope(),
        "token_present": cfg.token() is not None,
        "problems": cfg.problems,
    }
    bench_path = Path(db).parent / cfg.local_bench_path
    if bench_path.exists():
        conn = open_bench(bench_path)
        try:
            out["candidates"] = dict(conn.execute(
                "SELECT status, COUNT(*) FROM bench_candidates GROUP BY status").fetchall())
            out["records"] = dict(conn.execute(
                "SELECT verdict, COUNT(*) FROM eval_records GROUP BY verdict").fetchall())
            out["pulls"] = conn.execute("SELECT COUNT(*) FROM bench_pulls").fetchone()[0]
        finally:
            conn.close()
    else:
        out["local_bench"] = "not created yet — run `kaos bench harvest`"

    if _json_out(ctx, out):
        return
    console.print(f"[bold]Attraktor[/bold] — {'enabled' if cfg.enabled else '[dim]disabled[/dim]'} "
                  f"({out['mode']}, publish → {out['publish_scope']})")
    for k in ("candidates", "records", "pulls"):
        if k in out:
            console.print(f"  {k}: {out[k]}")
    for p in cfg.problems:
        console.print(f"  [yellow]•[/yellow] {p}")


@bench.command("harvest")
@click.option("--db", default=DEFAULT_DB, help="kaos.db path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="kaos.yaml path")
@click.pass_context
def bench_harvest(ctx, db: str, config_file: str):
    """Harvest validated-candidate learnings from this workspace (idempotent)."""
    import sqlite3 as _sq
    from kaos.bench.config import load_bench_config
    from kaos.bench.harvest import harvest_all
    from kaos.bench.schema import open_bench

    cfg = load_bench_config(config_file)
    kaos_conn = _sq.connect(f"file:{db}?mode=ro", uri=True)
    bench_conn = open_bench(Path(db).parent / cfg.local_bench_path)
    try:
        rep = harvest_all(kaos_conn, bench_conn)
    finally:
        kaos_conn.close()
        bench_conn.close()
    if _json_out(ctx, rep.to_dict()):
        return
    console.print(f"harvested: {rep.skills_harvested} skills, "
                  f"{rep.promotions_harvested} promotions, "
                  f"{rep.experiments_harvested} mechanism evals "
                  f"(E1 passed {rep.e1_passed}, rejected {rep.e1_rejected}, "
                  f"E0 accumulating {rep.e0_accumulating})")


@bench.command("validate")
@click.option("--db", default=DEFAULT_DB, help="kaos.db path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="kaos.yaml path")
@click.option("--limit", type=int, default=None, help="max candidates this pass")
@click.option("--no-model", is_flag=True, default=False,
              help="mint probe-validated mechanism evals only; skills stay E1")
@click.pass_context
def bench_validate(ctx, db: str, config_file: str, limit: int | None, no_model: bool):
    """Run pending candidates through the entry ladder (E2 replay probe).

    Mechanism evals mint directly (their pre-registered probe IS the validation
    — REJECT/VOID mint too; rejections are data). Skills/learnings run the
    three-arm held-out replay probe via the router; without a configured model
    they stay E1, counted, never silently dropped.
    """
    import sqlite3 as _sq
    from kaos.bench.config import load_bench_config
    from kaos.bench.schema import open_bench
    from kaos.bench.validate import completion_from_router, validate_pending

    cfg = load_bench_config(config_file)
    complete = None
    if not no_model:
        try:
            from kaos.router.gepa import GEPARouter
            router = GEPARouter.from_config(config_file)
            if getattr(router, "clients", None):
                complete = completion_from_router(router)
        except Exception:
            complete = None   # honest degradation: skills stay E1, counted below

    kaos_conn = _sq.connect(f"file:{db}?mode=ro", uri=True)
    bench_conn = open_bench(Path(db).parent / cfg.local_bench_path)
    try:
        rep = validate_pending(kaos_conn, bench_conn, complete=complete, limit=limit)
    finally:
        kaos_conn.close()
        bench_conn.close()

    if _json_out(ctx, rep.to_dict()):
        return
    console.print(
        f"minted {rep.minted_mechanism_evals} mechanism evals · "
        f"E2: {rep.e2_passed} passed, {rep.e2_rejected} rejected, "
        f"{rep.harness_inadmissible} harness-inadmissible, "
        f"{rep.not_runnable} not runnable · {rep.skipped_no_model} awaiting a model")
    for d in rep.details[:10]:
        console.print(f"  {d['candidate']}: {d['outcome']}")


@bench.command("rejections")
@click.option("--db", default=DEFAULT_DB, help="kaos.db path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="kaos.yaml path")
@click.option("--limit", default=20)
@click.pass_context
def bench_rejections(ctx, db: str, config_file: str, limit: int):
    """What has this workspace tried and rejected, and WHY (D0.1: rejections
    are first-class data — check here before re-trying a known-dead pattern)."""
    from kaos.bench.config import load_bench_config
    from kaos.bench.schema import open_bench

    cfg = load_bench_config(config_file)
    bench_path = Path(db).parent / cfg.local_bench_path
    if not bench_path.exists():
        if not _json_err(ctx, "no local bench yet — run `kaos bench harvest`"):
            console.print("[yellow]no local bench yet — run `kaos bench harvest`[/yellow]")
        return
    conn = open_bench(bench_path)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT source_ref, kind, status, rejection_reason, decided_at "
            "FROM bench_candidates WHERE status IN ('e1_rejected','e2_rejected','error') "
            "ORDER BY decided_at DESC LIMIT ?", (limit,))]
    finally:
        conn.close()
    if _json_out(ctx, {"rejections": rows}):
        return
    if not rows:
        console.print("no rejections recorded yet")
    for r in rows:
        console.print(f"  [red]✗[/red] {r['source_ref']} [{r['kind']}] — {r['rejection_reason']}")


@bench.command("push")
@click.option("--db", default=DEFAULT_DB, help="kaos.db path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="kaos.yaml path")
@click.option("--limit", type=int, default=25, help="max records this pass")
@click.pass_context
def bench_push(ctx, db: str, config_file: str, limit: int):
    """Push local validated records to the shared Attraktor bench.

    Needs bench.endpoint in kaos.yaml and the workspace token in the
    environment (default $KAOS_BENCH_TOKEN — generate it in the dashboard).
    Publish routing is decided server-side from the token's workspace tier;
    the server re-hashes every record's canonical bytes before storing.
    """
    from kaos.bench.config import load_bench_config
    from kaos.bench.remote import push_records
    from kaos.bench.schema import open_bench

    cfg = load_bench_config(config_file)
    bench_path = Path(db).parent / cfg.local_bench_path
    if not bench_path.exists():
        if not _json_err(ctx, "no local bench yet — run `kaos bench harvest`"):
            console.print("[yellow]no local bench yet — run `kaos bench harvest`[/yellow]")
        return
    bench_conn = open_bench(bench_path)
    try:
        rep = push_records(bench_conn, cfg, limit=limit)
    finally:
        bench_conn.close()
    if _json_out(ctx, rep.to_dict()):
        return
    console.print(f"pushed {rep.pushed} · duplicates {rep.duplicates} · "
                  f"refused {rep.refused} · errors {rep.errors}")
    for d in rep.details[:10]:
        console.print(f"  {d.get('record_cid', '')[:24]} {d.get('status', d.get('error', ''))}")


@bench.command("pull")
@click.argument("task_text")
@click.option("--db", default=DEFAULT_DB, help="kaos.db path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="kaos.yaml path")
@click.option("-k", type=int, default=3, help="max items")
@click.pass_context
def bench_pull(ctx, task_text: str, db: str, config_file: str, k: int):
    """Show what an agent starting TASK_TEXT would receive from the brain.

    Runs the real pipeline: remote fetch (verified + cached) when an endpoint
    is configured, then the local match/rank/serve path. This CLI pull is
    ledgered without an arm, so it never pollutes the binding probe's data.
    """
    from kaos.bench.config import load_bench_config
    from kaos.bench.fingerprint import Grain, Level, TaskShape, anchor_tokens
    from kaos.bench.pull import pull
    from kaos.bench.schema import open_bench

    cfg = load_bench_config(config_file)
    bench_conn = open_bench(Path(db).parent / cfg.local_bench_path)
    try:
        cached = 0
        if cfg.is_remote:
            from kaos.bench.remote import fetch_and_cache
            cached = fetch_and_cache(bench_conn, cfg, task_text=task_text)
        shape = TaskShape(m1=Level.UNKNOWN, m2=Level.PRESENT, m4=Level.UNKNOWN,
                          m2_grain=Grain.EPISODE,
                          m3_anchor_tokens=anchor_tokens(task_text))
        res = pull(bench_conn, agent_id="cli-pull", task_text=task_text,
                   task_shape=shape, k=k,
                   kinds=("skill", "learning", "mechanism_eval"))
    finally:
        bench_conn.close()

    out = {"remote_cached": cached, "withheld": res.withheld_count,
           "items": [{"record_cid": i.record_cid, "kind": i.kind,
                      "trust": i.trust_level, "fidelity": i.fidelity,
                      "name": (i.payload.get("name")
                               or (i.payload.get("payload") or {}).get("name")),
                      "lesson": ((i.payload.get("payload") or {}).get("lesson")
                                 or i.payload.get("lesson"))}
                     for i in res.items]}
    if _json_out(ctx, out):
        return
    if cached:
        console.print(f"[dim]cached {cached} new record(s) from the registry[/dim]")
    if not res.items:
        console.print("no matched learnings for this task "
                      f"({res.withheld_count} withheld by the transfer gate)")
    for i in out["items"]:
        console.print(f"[bold]{i['name']}[/bold] · T{i['trust']} · {i['fidelity']}")
        if i["lesson"]:
            console.print(f"  {i['lesson']}")


@bench.command("probe")
@click.option("--db", default=DEFAULT_DB, help="kaos.db path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="kaos.yaml path")
@click.option("--bind", is_flag=True, default=False,
              help="THE binding run: falsification self-test + write results.json")
@click.option("--out", default="benchmarks/demo_attraktor_loop_bench",
              help="output dir for results.json (with --bind)")
@click.pass_context
def bench_probe(ctx, db: str, config_file: str, bind: bool, out: str):
    """The loop's binding kill-gate probe (pre-registered, hash-locked).

    Without --bind: read-only progress surface — current per-gate status and
    the verdict-if-bound-now (VOID until the pre-registered floors are met).
    With --bind: runs the falsification self-test (ON := OFF must fail G1),
    computes the BINDING verdict, and writes results.json. No retune-and-rerun.
    """
    from demo_attraktor_loop_bench.probe_adapter import run_probe, status
    from kaos.bench.config import load_bench_config
    from kaos.bench.schema import open_bench

    cfg = load_bench_config(config_file)
    bench_path = Path(db).parent / cfg.local_bench_path
    if not bench_path.exists():
        if not _json_err(ctx, "no local bench yet — run `kaos bench harvest`"):
            console.print("[yellow]no local bench yet — run `kaos bench harvest`[/yellow]")
        return
    conn = open_bench(bench_path)
    try:
        rep = run_probe(conn, out_dir=out) if bind else status(conn)
    finally:
        conn.close()
    if _json_out(ctx, rep):
        return
    verdict = rep.get("verdict") or rep.get("verdict_if_bound_now")
    console.print(f"[bold]{rep.get('lock_name', rep.get('lock'))}[/bold] "
                  f"({'BINDING' if bind else 'progress'})")
    console.print(f"  episodes: {rep['episodes']}  wins: {rep['wins']}")
    console.print(f"  pulls: {rep['pulls']}  matched: {rep['matched_pulls']}")
    for g in rep["gates"]:
        mark = "[green]✓[/green]" if g["passed"] else "[red]✗[/red]"
        console.print(f"  {mark} {g['gate']} {g['name']}: {g['detail']}")
    if bind:
        st = "passed" if rep["self_test_passed"] else "[red]FAILED[/red]"
        console.print(f"  falsification self-test: {st}")
    console.print(f"  verdict{'' if bind else ' if bound now'}: [bold]{verdict}[/bold]")


@cli.group()
def mh():
    """Meta-Harness — automated harness optimization."""
    pass


@mh.command("stats")
@click.argument("search_agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def mh_stats(ctx, search_agent_id: str, db: str):
    """Read-only bootstrap stats over a completed search archive.

    For each evaluated candidate, computes the vs-incumbent correctness
    difference and its 95%% bootstrap CI, flagging which apparent improvements
    are within noise. Reads the archive only — never mutates the search.
    """
    from kaos import Kaos
    from kaos.metaharness.stats import compute_search_stats

    afs = Kaos(db_path=db)
    try:
        stats = compute_search_stats(afs, search_agent_id)
    finally:
        afs.close()

    if _json_out(ctx, stats.to_dict()):
        return

    console.print(f"[bold]Search[/bold] {search_agent_id}")
    console.print(f"objectives: {stats.objectives or '(none recorded)'}")
    console.print(f"incumbent: {stats.incumbent_id or '(none)'}\n")
    for c in sorted(stats.candidates, key=lambda x: (not x.is_incumbent, -x.accuracy)):
        tag = " [cyan](incumbent)[/cyan]" if c.is_incumbent else ""
        line = f"  {c.harness_id[:12]}…  acc={c.accuracy:.3f} (n={c.n_problems}){tag}"
        if c.mean_diff is not None:
            verdict = "[green]distinguishable[/green]" if c.distinguishable else "[dim]within noise[/dim]"
            line += (f"  Δvs-incumbent={c.mean_diff:+.3f} "
                     f"CI[{c.ci_lo:+.3f}, {c.ci_hi:+.3f}] {verdict}")
        console.print(line)
    for note in stats.notes:
        console.print(f"\n[yellow]•[/yellow] {note}")


@mh.command("search")
@click.option("--benchmark", "-b", required=True,
              type=click.Choice(["text_classify", "math_rag", "agentic_coding"]),
              help="Benchmark to optimize for")
@click.option("--iterations", "-n", default=20, help="Number of search iterations")
@click.option("--candidates", "-k", default=3, help="Candidates per iteration")
@click.option("--seed", "-s", multiple=True, help="Seed harness file paths")
@click.option("--proposer-model", help="Force model for proposer agent")
@click.option("--eval-model", help="Force model for evaluation")
@click.option("--max-parallel", default=4, help="Max parallel evaluations")
@click.option("--eval-subset", type=int, help="Subsample problems for faster search")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="Config file path")
@click.option("--background/--foreground", default=False, help="Run as detached background process")
@click.option("--dry-run", is_flag=True, default=False, help="Evaluate seeds only, report baseline scores")
@click.pass_context
def mh_search(ctx, benchmark, iterations, candidates, seed, proposer_model,
              eval_model, max_parallel, eval_subset, db, config_file, background, dry_run):
    """Run a meta-harness search to optimize a harness for a benchmark."""
    import subprocess as _sp

    if not Path(config_file).exists():
        if not _json_err(ctx, f"Config file not found: {config_file}"):
            console.print(f"[red]Config file not found:[/red] {config_file}")
        return

    if background:
        # Launch as detached worker process
        cmd = [
            sys.executable, "-m", "kaos.metaharness.worker",
            "--db", db,
            "--config-file", config_file,
            "--benchmark", benchmark,
            "--iterations", str(iterations),
            "--candidates", str(candidates),
            "--max-parallel", str(max_parallel),
        ]
        if eval_subset:
            cmd += ["--eval-subset", str(eval_subset)]
        if proposer_model:
            cmd += ["--proposer-model", proposer_model]
        for s in seed:
            cmd += ["--seed", s]

        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                _sp.CREATE_NEW_PROCESS_GROUP | _sp.DETACHED_PROCESS
            )
        else:
            kwargs["start_new_session"] = True

        import time as _time
        log_path = os.path.join(os.path.dirname(os.path.abspath(db)), f"kaos-worker-{int(_time.time())}.log")
        log_file = open(log_path, "w")
        proc = _sp.Popen(cmd, stdout=log_file, stderr=log_file, **kwargs)

        result = {
            "status": "running",
            "pid": proc.pid,
            "log_path": log_path,
            "message": f"Worker launched (PID {proc.pid}). Log: {log_path}",
        }
        if _json_out(ctx, result):
            return
        console.print(f"[green]Worker launched[/green] (PID {proc.pid})")
        console.print(f"  Log: {log_path}")
        console.print(f"  Poll with: kaos mh status <search_agent_id>")
        return

    # Foreground mode — run in-process
    from kaos.metaharness.search import MetaHarnessSearch
    from kaos.metaharness.harness import SearchConfig
    from kaos.metaharness.benchmarks import get_benchmark
    import kaos.metaharness.benchmarks.text_classify  # noqa: F401
    import kaos.metaharness.benchmarks.math_rag  # noqa: F401
    import kaos.metaharness.benchmarks.agentic_coding  # noqa: F401
    from kaos.router.gepa import GEPARouter

    afs = _get_afs(db)
    router = GEPARouter.from_config(config_file)

    config = SearchConfig(
        benchmark=benchmark,
        max_iterations=iterations,
        candidates_per_iteration=candidates,
        seed_harnesses=list(seed),
        proposer_model=proposer_model,
        evaluator_model=eval_model,
        max_parallel_evals=max_parallel,
        eval_subset_size=eval_subset,
    )

    bench = get_benchmark(benchmark)

    if not ctx.obj.get("json"):
        console.print(f"[cyan]Starting meta-harness search[/cyan]")
        console.print(f"  Benchmark: {benchmark}")
        console.print(f"  Iterations: {iterations}")
        console.print(f"  Candidates/iter: {candidates}")
        console.print(f"  Max parallel: {max_parallel}")

    search = MetaHarnessSearch(afs, router, bench, config)
    if ctx.params.get("dry_run"):
        if not ctx.obj.get("json"):
            console.print("[cyan]Dry-run: evaluating seeds only[/cyan]")
        result = asyncio.run(search.run_seeds_only())
    else:
        result = asyncio.run(search.run())

    result_data = {
        "search_agent_id": result.search_agent_id,
        "status": "completed",
        "summary": result.summary(),
        "total_harnesses": result.total_harnesses_evaluated,
        "duration_seconds": round(result.total_duration_seconds, 1),
        "frontier_size": len(result.frontier.points),
    }
    if not _json_out(ctx, result_data):
        console.print(f"\n[green]{result.summary()}[/green]")
    afs.close()


@mh.command("frontier")
@click.argument("search_agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def mh_frontier(ctx, search_agent_id, db):
    """Show the Pareto frontier of a meta-harness search."""
    afs = _get_afs(db)
    try:
        data = afs.read(search_agent_id, "/pareto/frontier.json")
        frontier = json.loads(data)

        if _json_out(ctx, frontier):
            return

        table = Table(title="Pareto Frontier")
        table.add_column("Harness ID", style="cyan", max_width=16)
        table.add_column("Iteration", justify="right")
        for obj in frontier.get("objectives", {}):
            table.add_column(obj.capitalize(), justify="right")

        for point in frontier.get("points", []):
            row = [point["harness_id"][:14] + "...", str(point.get("iteration", "?"))]
            for obj in frontier.get("objectives", {}):
                val = point.get("scores", {}).get(obj, 0)
                row.append(f"{val:.4f}")
            table.add_row(*row)

        console.print(table)
    except FileNotFoundError:
        if not _json_err(ctx, "No frontier found"):
            console.print("[red]No frontier found. Is this a valid search agent?[/red]")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@mh.command("inspect")
@click.argument("search_agent_id")
@click.argument("harness_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def mh_inspect(search_agent_id, harness_id, db):
    """Inspect a specific harness — source, scores, and trace summary."""
    afs = _get_afs(db)
    try:
        base = f"/harnesses/{harness_id}"

        # Source
        source = afs.read(search_agent_id, f"{base}/source.py").decode()
        console.print("[bold]Source Code:[/bold]")
        console.print(source)

        # Scores
        scores = json.loads(afs.read(search_agent_id, f"{base}/scores.json"))
        console.print(f"\n[bold]Scores:[/bold]")
        for k, v in scores.items():
            console.print(f"  {k}: {v:.4f}")

        # Metadata
        meta = json.loads(afs.read(search_agent_id, f"{base}/metadata.json"))
        console.print(f"\n[bold]Metadata:[/bold]")
        console.print(f"  Iteration: {meta.get('iteration', '?')}")
        console.print(f"  Parents: {meta.get('parent_ids', [])}")
        console.print(f"  Duration: {meta.get('duration_ms', 0)}ms")
        if meta.get("metadata", {}).get("rationale"):
            console.print(f"  Rationale: {meta['metadata']['rationale'][:200]}")

        # Trace summary
        try:
            trace_data = afs.read(search_agent_id, f"{base}/trace.jsonl").decode()
            lines = [l for l in trace_data.split("\n") if l.strip()]
            console.print(f"\n[bold]Trace:[/bold] {len(lines)} entries")
            for line in lines[:10]:
                entry = json.loads(line)
                console.print(f"  {entry.get('type', '?')}: {str(entry)[:80]}")
            if len(lines) > 10:
                console.print(f"  ... and {len(lines) - 10} more")
        except FileNotFoundError:
            console.print("\n[dim]No trace available[/dim]")

    except FileNotFoundError as e:
        console.print(f"[red]Not found: {e}[/red]")
    finally:
        afs.close()


@mh.command("status")
@click.argument("search_agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def mh_status(ctx, search_agent_id, db):
    """Show the status of a meta-harness search."""
    afs = _get_afs(db)
    try:
        info = afs.status(search_agent_id)
        iteration = afs.get_state_or(search_agent_id, "current_iteration", 0)
        harnesses = afs.ls(search_agent_id, "/harnesses")

        result = {
            "search_agent_id": search_agent_id,
            "status": info["status"],
            "pid": info.get("pid"),
            "current_iteration": iteration,
            "harnesses_evaluated": len(harnesses),
        }

        try:
            frontier = json.loads(
                afs.read(search_agent_id, "/pareto/frontier.json")
            )
            result["frontier_size"] = len(frontier.get("points", []))
        except FileNotFoundError:
            result["frontier_size"] = 0

        if _json_out(ctx, result):
            return

        console.print(f"[bold]Search Agent:[/bold] {search_agent_id[:14]}...")
        console.print(f"  Status: {info['status']}")
        console.print(f"  Current iteration: {iteration}")
        console.print(f"  Harnesses evaluated: {len(harnesses)}")
        console.print(f"  Frontier size: {result['frontier_size']}")

    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@mh.command("resume")
@click.argument("search_agent_id")
@click.option("--benchmark", "-b", required=True,
              help="Benchmark name (must match original search)")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="Config file path")
def mh_resume(search_agent_id, benchmark, db, config_file):
    """Resume an interrupted meta-harness search from its last iteration."""
    from kaos.metaharness.search import MetaHarnessSearch
    from kaos.metaharness.harness import SearchConfig
    from kaos.metaharness.benchmarks import get_benchmark
    import kaos.metaharness.benchmarks.text_classify  # noqa: F401
    import kaos.metaharness.benchmarks.math_rag  # noqa: F401
    import kaos.metaharness.benchmarks.agentic_coding  # noqa: F401
    import kaos.metaharness.benchmarks.paper_datasets  # noqa: F401
    from kaos.router.gepa import GEPARouter

    afs = _get_afs(db)

    if not Path(config_file).exists():
        console.print(f"[red]Config file not found:[/red] {config_file}")
        return

    router = GEPARouter.from_config(config_file)
    bench = get_benchmark(benchmark)
    config = SearchConfig(benchmark=benchmark)
    search = MetaHarnessSearch(afs, router, bench, config)

    console.print(f"[cyan]Resuming search {search_agent_id[:14]}...[/cyan]")

    result = asyncio.run(search.resume(search_agent_id))

    console.print(f"\n[green]{result.summary()}[/green]")
    afs.close()


@mh.command("lint")
@click.argument("search_agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def mh_lint(ctx, search_agent_id, db):
    """Health-check a search archive for issues."""
    afs = _get_afs(db)
    try:
        info = afs.status(search_agent_id)
        harness_dirs = afs.ls(search_agent_id, "/harnesses")
        issues_found = []

        # Check for harnesses with empty scores
        empty_scores = 0
        failed_harnesses = 0
        all_scores = {}
        for entry in harness_dirs:
            if not entry.get("is_dir"):
                continue
            hid = entry["name"]
            try:
                scores = json.loads(afs.read(search_agent_id, f"/harnesses/{hid}/scores.json").decode())
                meta = json.loads(afs.read(search_agent_id, f"/harnesses/{hid}/metadata.json").decode())
                if not scores:
                    empty_scores += 1
                if meta.get("error"):
                    failed_harnesses += 1
                all_scores[hid] = scores
            except FileNotFoundError:
                issues_found.append(f"Missing scores/metadata for harness {hid[:12]}")

        if empty_scores:
            issues_found.append(f"{empty_scores} harnesses have empty scores (evaluation failed)")
        if failed_harnesses:
            issues_found.append(f"{failed_harnesses} harnesses have errors in metadata")

        # Check for iteration errors
        iter_dirs = afs.ls(search_agent_id, "/iterations")
        error_iters = 0
        for entry in iter_dirs:
            if entry.get("is_dir"):
                try:
                    afs.read(search_agent_id, f"{entry['path']}/error.json")
                    error_iters += 1
                except FileNotFoundError:
                    pass
        if error_iters:
            issues_found.append(f"{error_iters} iterations had errors (proposer timeout or eval failure)")

        # Check frontier
        try:
            frontier = json.loads(afs.read(search_agent_id, "/pareto/frontier.json").decode())
            frontier_size = len(frontier.get("points", []))
            if frontier_size == 0:
                issues_found.append("Pareto frontier is empty — no successful harnesses")
        except FileNotFoundError:
            issues_found.append("No Pareto frontier found")
            frontier_size = 0

        result = {
            "search_agent_id": search_agent_id,
            "status": info["status"],
            "total_harnesses": len(harness_dirs),
            "frontier_size": frontier_size,
            "issues": issues_found,
            "health": "clean" if not issues_found else f"{len(issues_found)} issues",
        }
        if _json_out(ctx, result):
            return

        console.print(f"[bold]Lint: {search_agent_id[:14]}...[/bold]")
        console.print(f"  Status: {info['status']}")
        console.print(f"  Harnesses: {len(harness_dirs)}, Frontier: {frontier_size}")
        if issues_found:
            console.print(f"\n[yellow]{len(issues_found)} issues found:[/yellow]")
            for issue in issues_found:
                console.print(f"  - {issue}")
        else:
            console.print(f"\n[green]Clean — no issues found[/green]")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@mh.command("knowledge")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def mh_knowledge(ctx, db):
    """Show the persistent knowledge base — discoveries from all prior searches."""
    afs = _get_afs(db)
    try:
        knowledge_id = afs.get_or_create_singleton("kaos-knowledge")
        files = afs.ls(knowledge_id, "/discoveries") if afs.exists(knowledge_id, "/discoveries") else []

        benchmarks = []
        for entry in files:
            if entry.get("is_dir"):
                bname = entry["name"]
                try:
                    latest = json.loads(
                        afs.read(knowledge_id, f"/discoveries/{bname}/latest_search.json").decode()
                    )
                except FileNotFoundError:
                    latest = {}
                harnesses = afs.ls(knowledge_id, f"/discoveries/{bname}/harnesses") if afs.exists(knowledge_id, f"/discoveries/{bname}/harnesses") else []
                benchmarks.append({
                    "benchmark": bname,
                    "harnesses_stored": len(harnesses),
                    "latest_search": latest,
                })

        result = {"knowledge_agent_id": knowledge_id, "benchmarks": benchmarks}
        if _json_out(ctx, result):
            return

        console.print(f"[bold]Knowledge Agent:[/bold] {knowledge_id[:14]}...")
        if not benchmarks:
            console.print("[dim]No discoveries yet — run a search first[/dim]")
        for b in benchmarks:
            console.print(f"\n  [cyan]{b['benchmark']}[/cyan]")
            console.print(f"    Harnesses stored: {b['harnesses_stored']}")
            if b["latest_search"]:
                console.print(f"    Best scores: {b['latest_search'].get('best_scores', {})}")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


# ── Memory CLI (kaos memory ...) ──────────────────────────────────────────

@cli.group()
def memory():
    """Cross-agent memory store — write and search shared knowledge."""


@memory.command("write")
@click.argument("agent_id")
@click.argument("content")
@click.option("--type", "-t", "mem_type", default="observation",
              type=click.Choice(["observation", "result", "skill", "insight", "error"]),
              help="Memory type")
@click.option("--key", "-k", default=None, help="Optional human-readable key")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def memory_write(ctx, agent_id: str, content: str, mem_type: str, key: str, db: str):
    """Write a memory entry for AGENT_ID with CONTENT."""
    from kaos.memory import MemoryStore
    afs = _get_afs(db)
    try:
        mem = MemoryStore(afs.conn)
        mid = mem.write(agent_id=agent_id, content=content, type=mem_type, key=key)
        result = {"memory_id": mid, "agent_id": agent_id, "type": mem_type, "key": key}
        if _json_out(ctx, result):
            return
        console.print(f"[green]Memory #{mid} written[/green]  agent={agent_id[:14]}  type={mem_type}"
                      + (f"  key={key}" if key else ""))
    finally:
        afs.close()


@memory.command("search")
@click.argument("query")
@click.option("--limit", "-n", default=10, help="Max results")
@click.option("--type", "-t", "mem_type", default=None,
              type=click.Choice(["observation", "result", "skill", "insight", "error"]),
              help="Filter by type")
@click.option("--agent", "-a", default=None, help="Filter by agent_id")
@click.option("--rank",
              type=click.Choice(["bm25", "weighted"]),
              default="bm25",
              help="bm25 (default) or weighted (plasticity-aware: "
                   "retrieval frequency + recency decay reorder results)")
@click.option("--record-hits/--no-record-hits", default=False,
              help="Record retrieval as memory_hits rows so plasticity "
                   "learns which entries are actually consulted.")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def memory_search(ctx, query: str, limit: int, mem_type: str, agent: str,
                  rank: str, record_hits: bool, db: str):
    """Full-text search across shared memory (FTS5 + porter stemming,
    optionally plasticity-weighted)."""
    from kaos.memory import MemoryStore
    afs = _get_afs(db)
    try:
        mem = MemoryStore(afs.conn)
        hits = mem.search(query=query, limit=limit, type=mem_type,
                          agent_id=agent, rank=rank,
                          record_hits=record_hits,
                          requesting_agent_id=agent)
        if _json_out(ctx, [h.to_dict() for h in hits]):
            return
        if not hits:
            console.print("[dim]No results[/dim]")
            return
        if rank == "weighted":
            console.print("[magenta](weighted)[/magenta] "
                          f"[dim]query: {query!r}[/dim]")
        for h in hits:
            key_str = f"  [dim]key={h.key}[/dim]" if h.key else ""
            console.print(f"[bold cyan]#{h.memory_id}[/bold cyan]  "
                          f"[yellow]{h.type}[/yellow]  "
                          f"[dim]{h.agent_id[:14]}[/dim]  "
                          f"[dim]{h.created_at[:19]}[/dim]{key_str}")
            console.print(f"  {h.content[:120]}" + ("..." if len(h.content) > 120 else ""))
    finally:
        afs.close()


@memory.command("ls")
@click.option("--agent", "-a", default=None, help="Filter by agent_id")
@click.option("--type", "-t", "mem_type", default=None,
              type=click.Choice(["observation", "result", "skill", "insight", "error"]),
              help="Filter by type")
@click.option("--limit", "-n", default=20, help="Max results")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def memory_ls(ctx, agent: str, mem_type: str, limit: int, db: str):
    """List memory entries (most recent first)."""
    from kaos.memory import MemoryStore
    afs = _get_afs(db)
    try:
        mem = MemoryStore(afs.conn)
        entries = mem.list(agent_id=agent, type=mem_type, limit=limit)
        if _json_out(ctx, [e.to_dict() for e in entries]):
            return
        stats = mem.stats()
        console.print(f"[bold]Memory Store[/bold]  total={stats['total']}  "
                      + "  ".join(f"{k}={v}" for k, v in stats["by_type"].items()))
        if not entries:
            console.print("[dim]No entries[/dim]")
            return
        for e in entries:
            key_str = f"  [dim]{e.key}[/dim]" if e.key else ""
            console.print(f"  [cyan]#{e.memory_id}[/cyan]  [yellow]{e.type}[/yellow]  "
                          f"[dim]{e.agent_id[:14]}[/dim]  [dim]{e.created_at[:19]}[/dim]{key_str}")
            console.print(f"    {e.content[:100]}" + ("..." if len(e.content) > 100 else ""))
    finally:
        afs.close()


# ── Shared Log CLI (kaos log ...) ─────────────────────────────────────────

@cli.group("log")
def shared_log_group():
    """Shared coordination log — LogAct intent/vote/decide protocol."""


@shared_log_group.command("tail")
@click.option("--n", "-n", "count", default=20, help="Number of entries to show")
@click.option("--type", "-t", "log_type", default=None, help="Filter by entry type")
@click.option("--agent", "-a", default=None, help="Filter by agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def log_tail(ctx, count: int, log_type: str, agent: str, db: str):
    """Show the last N entries from the shared coordination log."""
    from kaos.shared_log import SharedLog
    afs = _get_afs(db)
    try:
        log = SharedLog(afs.conn)
        if log_type or agent:
            entries = log.read(type=log_type, agent_id=agent, limit=count)
        else:
            entries = log.tail(count)
        if _json_out(ctx, [e.to_dict() for e in entries]):
            return
        if not entries:
            console.print("[dim]Log is empty[/dim]")
            return
        TYPE_COLORS = {
            "intent": "cyan", "vote": "yellow", "decision": "green",
            "commit": "bold green", "result": "magenta", "abort": "red",
            "policy": "bold white", "mail": "blue",
        }
        for e in entries:
            color = TYPE_COLORS.get(e.type, "white")
            ref_str = f"  [dim]ref={e.ref_id}[/dim]" if e.ref_id else ""
            console.print(f"[dim]{e.position:4d}[/dim]  [{color}]{e.type:8s}[/{color}]  "
                          f"[dim]{e.agent_id[:14]}[/dim]  [dim]{e.created_at[:19]}[/dim]{ref_str}")
            payload_str = str(e.payload)
            console.print(f"       {payload_str[:100]}" + ("..." if len(payload_str) > 100 else ""))
    finally:
        afs.close()


@shared_log_group.command("ls")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def log_ls(ctx, db: str):
    """Show shared log statistics."""
    from kaos.shared_log import SharedLog
    afs = _get_afs(db)
    try:
        log = SharedLog(afs.conn)
        stats = log.stats()
        if _json_out(ctx, stats):
            return
        console.print(f"[bold]Shared Log[/bold]  total={stats['total']}")
        for t, n in stats["by_type"].items():
            console.print(f"  {t:12s} {n}")
    finally:
        afs.close()


# ── Skills CLI (kaos skills ...) ──────────────────────────────────────────

@cli.group("skills")
def skills_group():
    """Cross-agent skill library — save and search reusable solution patterns."""


@skills_group.command("save")
@click.option("--name", "-n", required=True, help="Skill name (snake_case)")
@click.option("--description", "-d", required=True, help="What the skill does and when to use it")
@click.option("--template", "-t", required=True, help="Prompt template (use {param} for variables)")
@click.option("--agent", "-a", default=None, help="Source agent_id")
@click.option("--tags", default=None, help="Comma-separated tags (e.g. classification,ensemble)")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_save(ctx, name: str, description: str, template: str, agent: str, tags: str, db: str):
    """Save a reusable skill to the shared library."""
    from kaos.skills import SkillStore
    afs = _get_afs(db)
    try:
        sk = SkillStore(afs.conn)
        tag_list = [t.strip() for t in tags.split(",")] if tags else []
        sid = sk.save(name=name, description=description, template=template,
                      source_agent_id=agent, tags=tag_list)
        skill = sk.get(sid)
        result = skill.to_dict() if skill else {"skill_id": sid}
        if _json_out(ctx, result):
            return
        params_str = ", ".join(skill.params()) if skill and skill.params() else "(no params)"
        console.print(f"[green]Skill #{sid} saved[/green]  name={name}  params=[{params_str}]")
        if tag_list:
            console.print(f"  tags: {', '.join(tag_list)}")
    finally:
        afs.close()


@skills_group.command("search")
@click.argument("query")
@click.option("--limit", "-n", default=10, help="Max results")
@click.option("--tag", default=None, help="Filter by tag")
@click.option("--rank",
              type=click.Choice(["bm25", "weighted"]),
              default="bm25",
              help="bm25 (default) or weighted (plasticity-aware: bm25 "
                   "× Wilson-lower-bound success × recency decay)")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_search(ctx, query: str, limit: int, tag: str, rank: str, db: str):
    """Full-text search across the skill library (FTS5 + BM25, optionally
    plasticity-weighted)."""
    from kaos.skills import SkillStore
    afs = _get_afs(db)
    try:
        sk = SkillStore(afs.conn)
        hits = sk.search(query=query, limit=limit, tag=tag, rank=rank)
        if _json_out(ctx, [s.to_dict() for s in hits]):
            return
        if not hits:
            console.print("[dim]No skills found[/dim]")
            return
        mode_tag = "[magenta](weighted)[/magenta] " if rank == "weighted" else ""
        console.print(f"{mode_tag}[dim]query: {query!r}[/dim]")
        for s in hits:
            rate = f"{s.success_count}/{s.use_count}" if s.use_count else "unused"
            tags_str = f"  [dim]{', '.join(s.tags)}[/dim]" if s.tags else ""
            console.print(f"[bold cyan]#{s.skill_id}[/bold cyan]  [yellow]{s.name}[/yellow]  "
                          f"[dim]{rate}[/dim]{tags_str}")
            console.print(f"  {s.description[:120]}" + ("..." if len(s.description) > 120 else ""))
            params = s.params()
            if params:
                console.print(f"  params: {{{', '.join(params)}}}")
    finally:
        afs.close()


@skills_group.command("ls")
@click.option("--tag", default=None, help="Filter by tag")
@click.option("--agent", "-a", default=None, help="Filter by source agent_id")
@click.option("--order", default="created_at",
              type=click.Choice(["created_at", "success_count", "use_count", "name"]),
              help="Sort order")
@click.option("--limit", "-n", default=20, help="Max results")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_ls(ctx, tag: str, agent: str, order: str, limit: int, db: str):
    """List skills in the library (most recent first)."""
    from kaos.skills import SkillStore
    afs = _get_afs(db)
    try:
        sk = SkillStore(afs.conn)
        skills = sk.list(tag=tag, source_agent_id=agent, order_by=order, limit=limit)
        if _json_out(ctx, [s.to_dict() for s in skills]):
            return
        stats = sk.stats()
        console.print(f"[bold]Skill Library[/bold]  total={stats['total']}")
        if not skills:
            console.print("[dim]No skills[/dim]")
            return
        t = Table(show_header=True, header_style="bold")
        t.add_column("ID", style="cyan", width=5)
        t.add_column("Name", style="yellow", width=24)
        t.add_column("Tags", width=20)
        t.add_column("Used", width=6)
        t.add_column("OK%", width=6)
        t.add_column("Description", width=40)
        for s in skills:
            rate = f"{s.success_count/s.use_count*100:.0f}%" if s.use_count else "-"
            t.add_row(
                str(s.skill_id),
                s.name,
                ", ".join(s.tags[:3]),
                str(s.use_count),
                rate,
                s.description[:40] + ("..." if len(s.description) > 40 else ""),
            )
        console.print(t)
    finally:
        afs.close()


@skills_group.command("apply")
@click.argument("skill_id", type=int)
@click.option("--param", "-p", "params", multiple=True,
              help="Template param as key=value (repeat for multiple)")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_apply(ctx, skill_id: int, params: tuple, db: str):
    """Render a skill template with parameters and print the result.

    Example: kaos skills apply 3 -p model=gpt4 -p voting=majority
    """
    from kaos.skills import SkillStore
    afs = _get_afs(db)
    try:
        sk = SkillStore(afs.conn)
        skill = sk.get(skill_id)
        if not skill:
            console.print(f"[red]Skill #{skill_id} not found[/red]")
            return
        kv: dict[str, str] = {}
        for p in params:
            if "=" in p:
                k, v = p.split("=", 1)
                kv[k.strip()] = v.strip()
        rendered = skill.apply(**kv)
        if _json_out(ctx, {"skill_id": skill_id, "name": skill.name, "rendered": rendered}):
            return
        console.print(f"[bold]Skill #{skill_id} — {skill.name}[/bold]")
        console.print(rendered)
    finally:
        afs.close()


@skills_group.command("outcome")
@click.argument("skill_id", type=int)
@click.option("--success/--fail", "success", default=None,
              help="Binary outcome")
@click.option("--quality", type=float, default=None,
              help="Continuous outcome in [0,1] (v0.8.3). When given, the "
                   "plasticity ranker uses it instead of the binary flag.")
@click.option("--agent", default=None, help="Attributing agent id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_outcome(ctx, skill_id: int, success: bool | None,
                   quality: float | None, agent: str, db: str):
    """Record the outcome of applying a skill.

    Examples:
        kaos skills outcome 5 --success
        kaos skills outcome 5 --quality 0.75
        kaos skills outcome 5 --fail --quality 0.0
    """
    from kaos.skills import SkillStore
    if success is None and quality is None:
        msg = "provide --success/--fail and/or --quality"
        if _json_err(ctx, msg):
            return
        console.print(f"[red]{msg}[/red]")
        ctx.exit(1)
        return
    # If only quality given, derive the binary flag from the midpoint so the
    # agent_skills aggregate still moves sensibly.
    eff_success = success if success is not None else (quality >= 0.5)
    afs = _get_afs(db)
    try:
        sk = SkillStore(afs.conn)
        try:
            sk.record_outcome(skill_id, eff_success, agent_id=agent,
                              quality=quality)
        except ValueError as e:
            if _json_err(ctx, str(e)):
                return
            console.print(f"[red]{e}[/red]")
            ctx.exit(1)
            return
        result = {"skill_id": skill_id, "success": eff_success,
                  "quality": quality}
        if _json_out(ctx, result):
            return
        q = f", quality={quality}" if quality is not None else ""
        console.print(f"[green]Outcome recorded[/green]  skill #{skill_id}  "
                      f"success={eff_success}{q}")
    finally:
        afs.close()


@skills_group.command("delete")
@click.argument("skill_id", type=int)
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_delete(ctx, skill_id: int, db: str):
    """Delete a skill by ID."""
    from kaos.skills import SkillStore
    afs = _get_afs(db)
    try:
        sk = SkillStore(afs.conn)
        removed = sk.delete(skill_id)
        result = {"skill_id": skill_id, "deleted": removed}
        if _json_out(ctx, result):
            return
        if removed:
            console.print(f"[green]Skill #{skill_id} deleted[/green]")
        else:
            console.print(f"[yellow]Skill #{skill_id} not found[/yellow]")
    finally:
        afs.close()


def _resolve_identifier(conn, kind: str, identifier: str) -> int | None:
    """Accept either a numeric id or a name/key and return the integer id."""
    if identifier.isdigit():
        return int(identifier)
    if kind == "skill":
        row = conn.execute(
            "SELECT skill_id FROM agent_skills WHERE name = ?",
            (identifier,),
        ).fetchone()
    elif kind == "memory":
        row = conn.execute(
            "SELECT memory_id FROM memory WHERE key = ?",
            (identifier,),
        ).fetchone()
    else:
        return None
    return int(row[0]) if row else None


@cli.group("dream")
def dream_group():
    """Neuroplasticity cycle — replay events, score entities, write a digest."""


@dream_group.command("run")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--dry-run/--apply", default=True,
              help="dry-run (default) = no DB mutations beyond the dream_runs "
                   "row; apply = also upsert episode_signals")
@click.option("--since", "since_ts", default=None,
              help="ISO timestamp; only replay agents created at/after this")
@click.option("--digest-dir", default=None,
              help="Where to write the markdown digest (default: Dreams/ next to DB)")
@click.option("--print-digest/--no-print-digest", default=True,
              help="Print the digest to stdout (default on)")
@click.pass_context
def dream_run(ctx, db: str, dry_run: bool, since_ts: str, digest_dir: str,
              print_digest: bool):
    """Run one dream cycle (replay + weights + narrative)."""
    from kaos.dream import DreamCycle
    if not Path(db).exists():
        msg = f"Database not found: {db}"
        if _json_err(ctx, msg):
            return
        console.print(f"[red]{msg}[/red]")
        ctx.exit(1)
        return

    afs = _get_afs(db)
    try:
        default_dir = Path(db).resolve().parent / "Dreams"
        cycle = DreamCycle(afs, digest_dir=digest_dir or default_dir)
        result = cycle.run(dry_run=dry_run, since_ts=since_ts)
    finally:
        afs.close()

    if _json_out(ctx, result.summary()):
        return

    console.print(
        f"[green]\u2714 Dream finished[/green]  "
        f"run_id=[cyan]{result.run_id}[/cyan]  "
        f"mode=[cyan]{result.mode}[/cyan]  "
        f"episodes=[cyan]{result.episodes}[/cyan]  "
        f"skills=[cyan]{result.skills_scored}[/cyan]  "
        f"memories=[cyan]{result.memories_scored}[/cyan]  "
        f"({result.phase_timings_ms.get('total_ms', 0)}ms)"
    )
    if result.digest_path:
        console.print(f"  Digest: [dim]{result.digest_path}[/dim]")
    if print_digest:
        console.print("")
        console.print(result.digest_markdown)


@dream_group.command("runs")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--limit", default=20, help="Number of past runs to list")
@click.pass_context
def dream_runs(ctx, db: str, limit: int):
    """List recent dream runs."""
    from kaos.dream.cycle import list_runs
    if not Path(db).exists():
        if _json_err(ctx, f"Database not found: {db}"):
            return
        console.print(f"[red]Database not found: {db}[/red]")
        ctx.exit(1)
        return
    afs = _get_afs(db)
    try:
        runs = list_runs(afs.conn, limit=limit)
    finally:
        afs.close()
    if _json_out(ctx, runs):
        return
    if not runs:
        console.print("[yellow]No dream runs yet.[/yellow]")
        return
    for r in runs:
        console.print(
            f"[cyan]#{r['run_id']}[/cyan]  {r['started_at']}  "
            f"[dim]{r['mode']}[/dim]  "
            f"episodes={r['episodes']} skills={r['skills_scored']} "
            f"memories={r['memories_scored']}"
        )


@dream_group.command("related")
@click.argument("kind", type=click.Choice(["skill", "memory"]))
@click.argument("identifier")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--limit", default=10, help="Max related entities to show")
@click.pass_context
def dream_related(ctx, kind: str, identifier: str, db: str, limit: int):
    """Show entities strongly associated with SKILL|MEMORY by name or id."""
    from kaos.dream.phases.associations import related
    if not Path(db).exists():
        if _json_err(ctx, f"Database not found: {db}"):
            return
        console.print(f"[red]Database not found: {db}[/red]")
        ctx.exit(1)
        return
    afs = _get_afs(db)
    try:
        ent_id = _resolve_identifier(afs.conn, kind, identifier)
        if ent_id is None:
            msg = f"{kind} not found: {identifier}"
            if _json_err(ctx, msg):
                return
            console.print(f"[red]{msg}[/red]")
            ctx.exit(1)
            return
        edges = related(afs.conn, kind, ent_id, limit=limit)
    finally:
        afs.close()

    if _json_out(ctx, [
        {
            "kind": e.kind_b, "id": e.id_b, "label": e.label_b,
            "weight": e.decayed_weight, "uses": e.uses,
            "last_seen": e.last_seen,
        } for e in edges
    ]):
        return
    if not edges:
        console.print(f"[yellow]No associations yet for {kind} '{identifier}'[/yellow]")
        return
    console.print(f"[bold]{len(edges)} associations[/bold] for {kind} [cyan]{identifier}[/cyan]:")
    for e in edges:
        console.print(
            f"  [dim]{e.kind_b}[/dim]  [cyan]{e.label_b}[/cyan]  "
            f"weight=[green]{e.decayed_weight:.2f}[/green]  uses={e.uses}"
        )


@dream_group.command("consolidate")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--apply/--dry-run", default=False,
              help="--apply executes safe proposals (prune/promote). "
                   "Merges are never auto-applied.")
@click.pass_context
def dream_consolidate(ctx, db: str, apply: bool):
    """Identify (and optionally execute) structural consolidation proposals."""
    from kaos.dream.phases.consolidation import run as run_consolidation
    from kaos.dream.phases.policies import run as run_policies
    if not Path(db).exists():
        if _json_err(ctx, f"Database not found: {db}"):
            return
        console.print(f"[red]Database not found: {db}[/red]")
        ctx.exit(1)
        return
    afs = _get_afs(db)
    try:
        cons = run_consolidation(afs.conn, dry_run=not apply,
                                 trigger_reason="manual")
        pol = run_policies(afs.conn, dry_run=not apply)
    finally:
        afs.close()

    payload = {
        "mode": "apply" if apply else "dry_run",
        "consolidation": {
            "total": len(cons.proposals),
            "promoted": cons.promoted,
            "pruned": cons.pruned,
            "merge_candidates": cons.merge_candidates,
            "applied": cons.applied,
        },
        "policies": {
            "promoted": pol.total_promoted,
            "existing_skipped": pol.skipped_existing,
        },
    }
    if _json_out(ctx, payload):
        return
    console.print(f"[bold]Consolidation ({'apply' if apply else 'dry_run'})[/bold]")
    console.print(f"  {cons.promoted} promote, {cons.pruned} prune, "
                  f"{cons.merge_candidates} merge candidates "
                  f"\u2192 applied [green]{cons.applied}[/green]")
    for p in cons.proposals[:12]:
        marker = {"promote": "\u2191", "prune": "\u2193",
                  "merge": "=", "split": "\u2502"}.get(p.kind, "-")
        applied = " [green](applied)[/green]" if p.applied else ""
        console.print(f"  {marker} {p.kind}: {p.rationale}{applied}")
    if pol.total_promoted or pol.skipped_existing:
        console.print(f"\n[bold]Policies[/bold]")
        console.print(f"  promoted {pol.total_promoted}  "
                      f"skipped {pol.skipped_existing} (already known)")


@dream_group.command("localize")
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def dream_localize(ctx, agent_id: str, db: str):
    """Find the earliest decisive error in a failed agent's trajectory.

    The visible error is rarely the root cause. This reconstructs the
    agent's tool_calls + shared_log timeline and points at the step where
    the outcome was effectively decided.
    """
    from kaos.dream.phases.localize import localize
    if not Path(db).exists():
        if _json_err(ctx, f"Database not found: {db}"):
            return
        console.print(f"[red]Database not found: {db}[/red]")
        ctx.exit(1)
        return
    afs = _get_afs(db)
    try:
        cs = localize(afs.conn, agent_id)
    finally:
        afs.close()
    if cs is None:
        if _json_out(ctx, {"agent_id": agent_id, "critical_step": None}):
            return
        console.print(f"[yellow]No failure found in {agent_id}'s "
                       f"trajectory — nothing to localize.[/yellow]")
        return
    payload = {
        "agent_id": cs.agent_id,
        "log_position": cs.log_position,
        "tool_call_id": cs.tool_call_id,
        "rationale": cs.rationale,
        "method": cs.method,
        "confidence": cs.confidence,
    }
    if _json_out(ctx, payload):
        return
    console.print(f"[bold]Critical step[/bold] for [cyan]{agent_id}[/cyan]")
    console.print(f"  position: {cs.log_position}  "
                  f"method: {cs.method}  "
                  f"confidence: {cs.confidence:.2f}")
    if cs.tool_call_id:
        console.print(f"  tool_call: {cs.tool_call_id}")
    console.print(f"  [dim]{cs.rationale}[/dim]")


@dream_group.command("merges")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--accept", type=int, default=None,
              help="Accept the merge with this proposal_id")
@click.option("--reject", type=int, default=None,
              help="Reject the merge with this proposal_id")
@click.option("--keep", type=int, default=None,
              help="When accepting: which skill_id to keep (default: lower id)")
@click.option("--reason", default=None,
              help="When rejecting: short rationale stored on the proposal")
@click.option("--limit", default=20, help="Max pending merges to list")
@click.pass_context
def dream_merges(ctx, db: str, accept: int, reject: int, keep: int,
                 reason: str, limit: int):
    """List pending merge proposals; accept or reject by proposal_id.

    Merge proposals are never auto-applied — an operator reviews them and
    runs one of:

        kaos dream merges --accept 7
        kaos dream merges --reject 9 --reason "serve different callers"
    """
    from kaos.dream.phases.consolidation import (
        accept_merge, list_pending_merges, reject_merge,
    )
    if not Path(db).exists():
        if _json_err(ctx, f"Database not found: {db}"):
            return
        console.print(f"[red]Database not found: {db}[/red]")
        ctx.exit(1)
        return
    if accept is not None and reject is not None:
        msg = "--accept and --reject are mutually exclusive"
        if _json_err(ctx, msg):
            return
        console.print(f"[red]{msg}[/red]")
        ctx.exit(1)
        return

    afs = _get_afs(db)
    try:
        if accept is not None:
            result = accept_merge(afs.conn, accept, keep_skill_id=keep)
        elif reject is not None:
            result = reject_merge(afs.conn, reject, reason=reason)
        else:
            result = {"pending": list_pending_merges(afs.conn, limit=limit)}
    finally:
        afs.close()

    if _json_out(ctx, result):
        return

    if "error" in result:
        console.print(f"[red]{result['error']}[/red]")
        ctx.exit(1)
        return
    if accept is not None:
        console.print(f"[bold green]Merge applied[/bold green]  "
                      f"proposal #{result['proposal_id']}")
        console.print(f"  kept skill #{result['kept_skill_id']}, "
                      f"retired skill #{result['retired_skill_id']}")
        console.print(f"  migrated {result['uses_migrated']} uses "
                      f"({result['successes_migrated']} successful)")
        return
    if reject is not None:
        console.print(f"[yellow]Merge rejected[/yellow]  "
                      f"proposal #{result['proposal_id']}")
        return

    pending = result.get("pending", [])
    if not pending:
        console.print("[dim]No pending merge proposals.[/dim]")
        return
    console.print(f"[bold]{len(pending)} pending merge proposal(s)[/bold]")
    for p in pending:
        ids = p.get("targets", {}).get("skill_ids", [])
        console.print(
            f"  [cyan]#{p['proposal_id']}[/cyan]  "
            f"skills {ids}  "
            f"[dim]{p.get('created_at', '')}[/dim]"
        )
        if p.get("rationale"):
            console.print(f"    {p['rationale']}")


@dream_group.command("diagnose")
@click.argument("fp_id", type=int)
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--category",
              type=click.Choice(["transient", "config", "code", "infra", "unknown"]),
              help="Manually set the category (overrides heuristic diagnosis)")
@click.option("--root-cause", help="Human-readable root cause description")
@click.option("--action", help="Suggested action")
@click.pass_context
def dream_diagnose(ctx, fp_id: int, db: str, category: str, root_cause: str,
                   action: str):
    """Show or set the diagnosis for a failure fingerprint."""
    import sqlite3 as _sq
    if not Path(db).exists():
        if _json_err(ctx, f"Database not found: {db}"):
            return
        console.print(f"[red]Database not found: {db}[/red]")
        ctx.exit(1)
        return
    afs = _get_afs(db)
    try:
        if category:
            from kaos.dream.phases.failures import set_category
            ok = set_category(afs.conn, fp_id, category=category,
                              root_cause=root_cause,
                              suggested_action=action)
            if not ok:
                msg = f"fp_id {fp_id} not found"
                if _json_err(ctx, msg):
                    return
                console.print(f"[red]{msg}[/red]")
                ctx.exit(1)
                return

        conn = afs.conn
        conn.row_factory = _sq.Row
        row = conn.execute(
            "SELECT fp_id, fingerprint, tool_name, example_error, count, "
            "category, root_cause, suggested_action, diagnostic_method, "
            "diagnosed_at, fix_attempts, fix_success_count, fix_summary "
            "FROM failure_fingerprints WHERE fp_id = ?",
            (fp_id,),
        ).fetchone()
    finally:
        afs.close()

    if row is None:
        msg = f"fp_id {fp_id} not found"
        if _json_err(ctx, msg):
            return
        console.print(f"[red]{msg}[/red]")
        ctx.exit(1)
        return

    payload = dict(row)
    if _json_out(ctx, payload):
        return

    console.print(f"[bold cyan]Fingerprint #{fp_id}[/bold cyan]  "
                  f"tool=[magenta]{payload['tool_name']}[/magenta]  "
                  f"count={payload['count']}")
    console.print(f"  error:    [dim]{payload['example_error']}[/dim]")
    console.print(f"  category: [yellow]{payload['category']}[/yellow]  "
                  f"(method: {payload.get('diagnostic_method') or 'not diagnosed'})")
    if payload["root_cause"]:
        console.print(f"  cause:    {payload['root_cause']}")
    if payload["suggested_action"]:
        console.print(f"  action:   {payload['suggested_action']}")
    attempts = payload.get("fix_attempts", 0) or 0
    if attempts:
        rate = (payload.get("fix_success_count", 0) or 0) / attempts
        console.print(f"  fix:      "
                      f"{payload.get('fix_success_count', 0)}/{attempts} = "
                      f"{rate * 100:.0f}% success rate")


@dream_group.command("fix-outcome")
@click.argument("fp_id", type=int)
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--succeeded/--failed", required=True,
              help="Did applying the known fix actually resolve the error?")
@click.pass_context
def dream_fix_outcome(ctx, fp_id: int, db: str, succeeded: bool):
    """Record whether a previously-suggested fix actually worked.

    Agents should call this after trying a known fix. If the fix's
    success rate drops below 50% after 5+ attempts, it auto-downgrades
    so future agents stop applying a broken suggestion.
    """
    from kaos.dream.phases.failures import record_fix_outcome
    if not Path(db).exists():
        if _json_err(ctx, f"Database not found: {db}"):
            return
        console.print(f"[red]Database not found: {db}[/red]")
        ctx.exit(1)
        return
    afs = _get_afs(db)
    try:
        result = record_fix_outcome(afs.conn, fp_id, succeeded=succeeded)
    finally:
        afs.close()
    if _json_out(ctx, result):
        return
    console.print(f"[bold]Fix outcome recorded[/bold]  fp_id={fp_id}")
    console.print(f"  attempts: {result.get('fix_attempts')}  "
                  f"successes: {result.get('fix_success_count')}  "
                  f"rate: {(result.get('fix_success_rate') or 0) * 100:.0f}%")
    if result.get("downgraded"):
        console.print("  [yellow]Fix DOWNGRADED \u2014 success rate below "
                      "threshold. Future agents won't get this suggestion.[/yellow]")


@dream_group.command("systemic")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--ack", type=int, default=None,
              help="Acknowledge alert by ID (marks as seen but not resolved)")
@click.option("--resolve", type=int, default=None,
              help="Mark alert as resolved by ID")
@click.option("--by", default=None,
              help="Who's acking/resolving (stored in acked_by/resolved_by)")
@click.pass_context
def dream_systemic(ctx, db: str, ack: int, resolve: int, by: str):
    """List active systemic alerts; ack/resolve by ID."""
    from kaos.dream.phases.failures import (
        ack_alert, list_active_alerts, resolve_alert,
    )
    if not Path(db).exists():
        if _json_err(ctx, f"Database not found: {db}"):
            return
        console.print(f"[red]Database not found: {db}[/red]")
        ctx.exit(1)
        return
    afs = _get_afs(db)
    try:
        if ack is not None:
            ok = ack_alert(afs.conn, ack, acked_by=by)
            if _json_out(ctx, {"alert_id": ack, "acked": ok}):
                return
            console.print(f"{'acked' if ok else 'not found'}: alert #{ack}")
            return
        if resolve is not None:
            ok = resolve_alert(afs.conn, resolve, resolved_by=by)
            if _json_out(ctx, {"alert_id": resolve, "resolved": ok}):
                return
            console.print(f"{'resolved' if ok else 'not found'}: alert #{resolve}")
            return
        alerts = list_active_alerts(afs.conn)
    finally:
        afs.close()

    if _json_out(ctx, alerts):
        return
    if not alerts:
        console.print("[green]No active systemic alerts.[/green]")
        return
    console.print(f"[bold red]{len(alerts)} active systemic alert(s)[/bold red]")
    for a in alerts:
        acked = f" [dim](acked by {a['acked_by'] or '?'})[/dim]" if a.get("acked_at") else ""
        console.print(
            f"  [cyan]#{a['alert_id']}[/cyan]  "
            f"detected {a['detected_at']}  "
            f"[yellow]{a['agent_count']} agents[/yellow] hit "
            f"`{a['tool_name']}` in {a['window_seconds']}s{acked}"
        )
        if a.get("root_cause"):
            console.print(f"    cause: {a['root_cause']}")


@dream_group.command("failures")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--min-count", default=2, help="Only show fingerprints seen N+ times")
@click.option("--taxonomy-class",
              type=click.Choice(["memory", "reflection", "planning",
                                 "action", "system", "unknown"]),
              default=None,
              help="Filter to one reasoning-class taxonomy bucket (v0.8.3)")
@click.pass_context
def dream_failures(ctx, db: str, min_count: int, taxonomy_class: str | None):
    """List recurring failure fingerprints."""
    from kaos.dream.phases.failures import run as run_failures
    if not Path(db).exists():
        if _json_err(ctx, f"Database not found: {db}"):
            return
        console.print(f"[red]Database not found: {db}[/red]")
        ctx.exit(1)
        return
    afs = _get_afs(db)
    try:
        report = run_failures(afs.conn, min_count_for_recurring=min_count)
    finally:
        afs.close()
    # Also fetch category + taxonomy info per fp_id. taxonomy_* columns
    # arrived in v8; fall back gracefully on older databases.
    import sqlite3 as _sq
    afs2 = _get_afs(db)
    try:
        conn = afs2.conn
        conn.row_factory = _sq.Row
        try:
            cat_rows = {
                r["fp_id"]: dict(r) for r in conn.execute(
                    "SELECT fp_id, category, root_cause, suggested_action, "
                    "taxonomy_class, taxonomy_subclass "
                    "FROM failure_fingerprints"
                ).fetchall()
            }
        except _sq.OperationalError:
            cat_rows = {
                r["fp_id"]: dict(r) for r in conn.execute(
                    "SELECT fp_id, category, root_cause, suggested_action "
                    "FROM failure_fingerprints"
                ).fetchall()
            }
    finally:
        afs2.close()

    recurring = report.recurring
    if taxonomy_class is not None:
        recurring = [
            e for e in recurring
            if (cat_rows.get(e.fp_id, {}).get("taxonomy_class")
                == taxonomy_class)
        ]

    payload = []
    for e in recurring:
        info = cat_rows.get(e.fp_id, {})
        payload.append({
            "fp_id": e.fp_id, "fingerprint": e.fingerprint,
            "tool": e.tool_name, "count": e.count,
            "category": info.get("category", "unknown"),
            "taxonomy_class": info.get("taxonomy_class"),
            "taxonomy_subclass": info.get("taxonomy_subclass"),
            "root_cause": info.get("root_cause"),
            "suggested_action": info.get("suggested_action"),
            "has_fix": bool(e.fix_summary or e.fix_skill_id),
            "example": e.example_error,
            "last_seen": e.last_seen,
        })
    if _json_out(ctx, payload):
        return
    if not recurring:
        if taxonomy_class:
            console.print(f"[yellow]No recurring failures in taxonomy "
                          f"'{taxonomy_class}'[/yellow]")
        else:
            console.print("[yellow]No recurring failures[/yellow]")
        return
    console.print(f"[bold]{report.total_fingerprints} distinct failure fingerprints[/bold] "
                  f"({len(recurring)} shown):")
    for e in recurring:
        info = cat_rows.get(e.fp_id, {})
        category = info.get("category") or "unknown"
        cat_colour = {"infra": "red", "config": "yellow", "code": "magenta",
                      "transient": "cyan", "unknown": "white"}.get(category, "white")
        tax = info.get("taxonomy_class")
        tax_str = f" [blue]\u29bf{tax}[/blue]" if tax else ""
        fix = "[green](has fix)[/green]" if e.fix_summary or e.fix_skill_id else ""
        console.print(f"  [cyan]#{e.fp_id}[/cyan] "
                      f"[{cat_colour}]{category}[/{cat_colour}]{tax_str} "
                      f"`{e.fingerprint}` "
                      f"{e.tool_name or '?'} \u00d7{e.count} {fix}")
        if info.get("root_cause"):
            console.print(f"    cause: {info['root_cause']}")
        elif e.example_error:
            console.print(f"    [dim]{e.example_error[:100]}[/dim]")


@dream_group.command("show")
@click.argument("run_id", type=int)
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def dream_show(ctx, run_id: int, db: str):
    """Show the digest and metadata for a past dream run."""
    from kaos.dream.cycle import get_run
    if not Path(db).exists():
        if _json_err(ctx, f"Database not found: {db}"):
            return
        console.print(f"[red]Database not found: {db}[/red]")
        ctx.exit(1)
        return
    afs = _get_afs(db)
    try:
        run = get_run(afs.conn, run_id)
    finally:
        afs.close()
    if run is None:
        if _json_err(ctx, f"Run {run_id} not found"):
            return
        console.print(f"[yellow]Run #{run_id} not found[/yellow]")
        ctx.exit(1)
        return
    if _json_out(ctx, run):
        return
    console.print(f"[bold cyan]Dream run #{run_id}[/bold cyan]  ({run['mode']})")
    console.print(f"  Started:  {run['started_at']}")
    console.print(f"  Finished: {run['finished_at']}")
    console.print(f"  Window:   {run['since_ts'] or 'all-time'}")
    console.print(f"  Episodes: {run['episodes']}  "
                  f"Skills: {run['skills_scored']}  "
                  f"Memories: {run['memories_scored']}")
    console.print(f"  Timings:  {run['phase_timings']}")
    if run.get("digest_path"):
        p = Path(run["digest_path"])
        if p.exists():
            console.print("")
            console.print(p.read_text(encoding="utf-8"))
        else:
            console.print(f"  [yellow]Digest file not found on disk: {p}[/yellow]")


@cli.group("ideal-state")
def isa_group():
    """Ideal State Artifacts — declare what 'done' looks like upfront,
    verify per-criterion at completion (v0.8.3)."""


@isa_group.command("create")
@click.argument("title")
@click.option("--agent", required=True, help="Owning agent id")
@click.option("--summary", default="", help="One-line 'done' summary")
@click.option("--criterion", "-c", "criteria", multiple=True, required=True,
              help="A criterion (repeat for several)")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def isa_create(ctx, title: str, agent: str, summary: str,
               criteria: tuple, db: str):
    """Create an ISA with one or more criteria.

    Example:
        kaos ideal-state create "Ship refund endpoint" --agent a1 \\
            -c "returns 201 on valid input" \\
            -c "duplicate request is idempotent"
    """
    from kaos.ideal_state import IdealStateStore
    afs = _get_afs(db)
    try:
        store = IdealStateStore(afs.conn)
        try:
            isa_id = store.create(agent, title, summary or title,
                                  [{"criterion": c} for c in criteria])
        except ValueError as e:
            if _json_err(ctx, str(e)):
                return
            console.print(f"[red]{e}[/red]")
            ctx.exit(1)
            return
        result = {"isa_id": isa_id, "title": title,
                  "criteria": len(criteria)}
        if _json_out(ctx, result):
            return
        console.print(f"[green]ISA #{isa_id}[/green] created — "
                      f"{len(criteria)} criteria")
    finally:
        afs.close()


@isa_group.command("mark")
@click.argument("isc_id", type=int)
@click.option("--passed", "status", flag_value="passed")
@click.option("--failed", "status", flag_value="failed")
@click.option("--skipped", "status", flag_value="skipped")
@click.option("--taxonomy", default=None,
              help="When --failed: reasoning-class (Track B1)")
@click.option("--reason", default=None, help="Optional note")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def isa_mark(ctx, isc_id: int, status: str, taxonomy: str, reason: str,
             db: str):
    """Mark a single criterion passed / failed / skipped."""
    from kaos.ideal_state import IdealStateStore
    if not status:
        msg = "specify one of --passed / --failed / --skipped"
        if _json_err(ctx, msg):
            return
        console.print(f"[red]{msg}[/red]")
        ctx.exit(1)
        return
    afs = _get_afs(db)
    try:
        store = IdealStateStore(afs.conn)
        store.mark(isc_id, status, failure_taxonomy=taxonomy, note=reason)
        if _json_out(ctx, {"isc_id": isc_id, "status": status}):
            return
        console.print(f"[green]ISC #{isc_id}[/green] -> {status}")
    finally:
        afs.close()


@isa_group.command("show")
@click.argument("isa_id", type=int)
@click.option("--finalize", is_flag=True,
              help="Compute + persist overall status before showing")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def isa_show(ctx, isa_id: int, finalize: bool, db: str):
    """Show an ISA and its criteria."""
    from kaos.ideal_state import IdealStateStore
    afs = _get_afs(db)
    try:
        store = IdealStateStore(afs.conn)
        if finalize:
            store.finalize(isa_id)
        isa = store.get(isa_id)
        if isa is None:
            if _json_err(ctx, f"ISA {isa_id} not found"):
                return
            console.print(f"[red]ISA {isa_id} not found[/red]")
            ctx.exit(1)
            return
        if _json_out(ctx, isa.to_dict()):
            return
        q = isa.quality
        console.print(f"[bold]ISA #{isa.isa_id}[/bold] {isa.title}  "
                      f"[dim]({isa.overall_status or 'pending'})[/dim]")
        console.print(f"  {isa.summary}")
        if q is not None:
            console.print(f"  quality: [cyan]{q:.2f}[/cyan]")
        for c in isa.criteria:
            colour = {"passed": "green", "failed": "red",
                      "skipped": "yellow"}.get(c.status, "white")
            tx = f" [blue]⦿{c.failure_taxonomy}[/blue]" if c.failure_taxonomy else ""
            console.print(f"  [{colour}]{c.status:>7}[/{colour}] "
                          f"#{c.isc_id} {c.criterion}{tx}")
    finally:
        afs.close()


@isa_group.command("list")
@click.option("--agent", default=None, help="Filter by agent")
@click.option("--open", "open_only", is_flag=True,
              help="Only ISAs still pending")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def isa_list(ctx, agent: str, open_only: bool, db: str):
    """List ISAs."""
    from kaos.ideal_state import IdealStateStore
    afs = _get_afs(db)
    try:
        store = IdealStateStore(afs.conn)
        isas = (store.list_open(agent) if open_only
                else store.list_all(agent))
        payload = [{"isa_id": i.isa_id, "title": i.title,
                    "status": i.overall_status,
                    "criteria": len(i.criteria),
                    "quality": i.quality} for i in isas]
        if _json_out(ctx, payload):
            return
        if not isas:
            console.print("[dim]No ISAs.[/dim]")
            return
        for i in isas:
            st = i.overall_status or "pending"
            console.print(f"  [cyan]#{i.isa_id}[/cyan] [{st}] "
                          f"{i.title}  ({len(i.criteria)} criteria)")
    finally:
        afs.close()


@cli.group("obsidian")
def obsidian_group():
    """Export a KAOS database to an Obsidian-compatible markdown vault."""


@obsidian_group.command("export")
@click.option("--vault", required=True, type=click.Path(),
              help="Path to the vault directory (created if missing)")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--clean", is_flag=True, default=False,
              help="Wipe generated directories/files before export (preserves "
                   ".obsidian/workspace* and any hand-written notes outside "
                   "the owned folders).")
@click.pass_context
def obsidian_export(ctx, vault: str, db: str, clean: bool):
    """Render agents, skills, memory, checkpoints, and the shared log as a vault."""
    from kaos.obsidian import VaultExporter

    if not Path(db).exists():
        msg = f"Database not found: {db}"
        if _json_err(ctx, msg):
            return
        console.print(f"[red]{msg}[/red]")
        ctx.exit(1)
        return

    exporter = VaultExporter(db_path=db, vault_path=vault)
    stats = exporter.export_all(clean=clean)

    result = {
        "vault": str(exporter.vault_path),
        "db": db,
        "agents": stats.agents,
        "skills": stats.skills,
        "memories": stats.memories,
        "checkpoints": stats.checkpoints,
        "log_entries": stats.log_entries,
        "files_written": stats.files_written,
    }
    if _json_out(ctx, result):
        return
    console.print(f"[green]\u2714 Vault exported:[/green] {exporter.vault_path}")
    console.print(
        f"  {stats.agents} agents  \u00b7  {stats.skills} skills  \u00b7  "
        f"{stats.memories} memories  \u00b7  {stats.checkpoints} checkpoints  \u00b7  "
        f"{stats.log_entries} log entries"
    )
    console.print(f"  [dim]{stats.files_written} files written[/dim]")
    console.print(
        "\n  Open the folder in Obsidian: "
        "[cyan]Manage Vaults \u2192 Open folder as vault \u2192 select the path above[/cyan]"
    )


@obsidian_group.command("info")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def obsidian_info(ctx, db: str):
    """Preview what would be exported without writing anything."""
    import sqlite3 as _sqlite3
    if not Path(db).exists():
        msg = f"Database not found: {db}"
        if _json_err(ctx, msg):
            return
        console.print(f"[red]{msg}[/red]")
        ctx.exit(1)
        return

    conn = _sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = _sqlite3.Row
    try:
        counts: dict[str, int] = {}
        for table, label in [
            ("agents", "agents"),
            ("agent_skills", "skills"),
            ("memory", "memories"),
            ("checkpoints", "checkpoints"),
            ("shared_log", "log_entries"),
        ]:
            try:
                counts[label] = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            except _sqlite3.OperationalError:
                counts[label] = 0
    finally:
        conn.close()

    if _json_out(ctx, counts):
        return
    console.print(f"[bold]Export preview for[/bold] {db}")
    for key, n in counts.items():
        console.print(f"  {key:<14} {n}")


@cli.command("plugins")
@click.pass_context
def plugins_cmd(ctx):
    """List installed KAOS plugins (entry-point group 'kaos.plugins')."""
    from kaos.plugins import get_registry
    reg = get_registry()
    data = {
        "loaded": reg.loaded,
        "errors": reg.errors,
        "providers": sorted(reg.providers),
        "benchmarks": sorted(reg.benchmarks),
        "mcp_tools": sorted(
            t["name"] for pack in reg.mcp_tool_packs for t in pack.tools
        ),
        "fleet_adapters": sorted(reg.fleet_adapters),
        "dream_phases": sorted(reg.dream_phases),
    }
    if _json_out(ctx, data):
        return
    if not reg.loaded and not reg.errors:
        console.print(
            "No plugins installed. A plugin is any package exposing an "
            "entry point in the [bold]kaos.plugins[/bold] group."
        )
        return
    for name in reg.loaded:
        console.print(f"[green]loaded[/green]  {name}")
    for name, err in reg.errors.items():
        console.print(f"[red]failed[/red]  {name}: {err}")
    for label, items in [
        ("providers", data["providers"]),
        ("benchmarks", data["benchmarks"]),
        ("mcp tools", data["mcp_tools"]),
        ("fleet adapters", data["fleet_adapters"]),
        ("dream phases", data["dream_phases"]),
    ]:
        if items:
            console.print(f"  {label}: {', '.join(items)}")


def main() -> None:
    """Console-script entry point (v2.0).

    Turns a missing optional dependency into one actionable install line
    instead of a traceback — G1.2 of the v0.11/v2.0 adoption roadmap.
    """
    from kaos._extras import MissingExtraError
    try:
        cli()
    except MissingExtraError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
