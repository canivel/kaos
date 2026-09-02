/**
 * pi-kaos — KAOS flight recorder + team memory for Pi.
 *
 * Every hook shells out to the `kaos` CLI and treats any failure (kaos not
 * installed, no kaos.db, timeout) as a silent no-op. Pi must never stall or
 * crash because the recorder is unavailable.
 *
 * Latency budgets (blocking hooks only):
 *   session_start       ≤ 450 ms  (journal open + no injection)
 *   before_agent_start  ≤ 450 ms  (memory search → injected message)
 *   tool_result / turn_end are journal writes only; same 450 ms cap, but
 *   nothing waits on their output.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { spawnSync } from "node:child_process";

const KAOS_BIN = process.env.KAOS_BIN ?? "kaos";
const AGENT = "pi";
const TIMEOUT_MS = 450;
const QUERY_CHARS = 120;

type JournalEvent = "session_start" | "tool_use" | "turn_end" | "session_stop";

/** Run `kaos <args>` with JSON on stdin. Returns stdout or "" on any failure. */
function kaos(args: string[], stdin?: unknown): string {
  try {
    const r = spawnSync(KAOS_BIN, args, {
      input: stdin === undefined ? undefined : JSON.stringify(stdin),
      encoding: "utf8",
      timeout: TIMEOUT_MS,
      windowsHide: true,
    });
    if (r.error || r.status !== 0) return "";
    return r.stdout ?? "";
  } catch {
    return "";
  }
}

function journal(event: JournalEvent, sessionId: string, payload: unknown): void {
  kaos(
    ["journal", "append", "--agent", AGENT, "--session", sessionId, "--event", event, "--stdin"],
    payload,
  );
}

function recall(query: string, limit = 5): string {
  const q = query.replace(/\s+/g, " ").trim().slice(0, QUERY_CHARS);
  if (!q) return "";
  return kaos(["memory", "search", q, "-n", String(limit), "--rank", "weighted", "--format", "inject"]).trim();
}

function sessionIdOf(ctx: { sessionManager: { getSessionId(): string } }): string {
  try {
    return ctx.sessionManager.getSessionId();
  } catch {
    return "unknown";
  }
}

export default function (pi: ExtensionAPI) {
  // Session opened (startup / reload / new / resume / fork) → journal it.
  pi.on("session_start", async (event, ctx) => {
    journal("session_start", sessionIdOf(ctx), { reason: event.reason, cwd: ctx.cwd });
  });

  // Before each agent turn → inject the top weighted memories for this prompt.
  pi.on("before_agent_start", async (event, ctx) => {
    const block = recall(event.prompt);
    if (!block) return;
    return {
      message: {
        customType: "kaos-memory",
        content: block,
        display: false,
      },
    };
  });

  // Every tool result → append to the audit journal (fire-and-forget).
  pi.on("tool_result", async (event, ctx) => {
    journal("tool_use", sessionIdOf(ctx), {
      tool_name: event.toolName,
      tool_call_id: event.toolCallId,
      input: event.input,
      is_error: event.isError ?? false,
      cwd: ctx.cwd,
    });
  });

  // Turn finished → journal the turn index and how many tools ran.
  pi.on("turn_end", async (event, ctx) => {
    journal("turn_end", sessionIdOf(ctx), {
      turn_index: event.turnIndex,
      tool_results: Array.isArray(event.toolResults) ? event.toolResults.length : 0,
    });
  });

  // Session closing → journal the stop so the recorder has a clean end mark.
  pi.on("session_shutdown", async (_event, ctx) => {
    journal("session_stop", sessionIdOf(ctx), { cwd: ctx.cwd });
  });

  // /kaos-recall <query> — search team memory from inside Pi.
  pi.registerCommand("kaos-recall", {
    description: "Search KAOS team memory (weighted by what actually worked)",
    handler: async (args, ctx) => {
      const block = recall(String(args ?? ""), 5);
      ctx.ui.notify(block || "kaos: no matching memory (or kaos not installed)", block ? "info" : "warning");
    },
  });
}
