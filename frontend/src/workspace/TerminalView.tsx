import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Play, RefreshCw, Send, Square } from "lucide-react";

import { api } from "../api/client";
import type { TerminalEvent, TerminalPayload, TerminalStatus } from "../api/types";
import { Orb } from "../Orb";


const STATUS_LABELS: Record<TerminalStatus, string> = {
  idle: "idle",
  running: "running",
  completed: "completed",
  failed: "failed",
  stopped: "stopped",
  timed_out: "timed out",
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Terminal 请求失败。";
}

function mergeEvents(current: TerminalEvent[], next: TerminalEvent[]): TerminalEvent[] {
  if (!next.length) return current;
  const seen = new Set(current.map((event) => event.sequence));
  return [...current, ...next.filter((event) => !seen.has(event.sequence))].sort(
    (left, right) => left.sequence - right.sequence,
  );
}

export function TerminalView() {
  const [terminal, setTerminal] = useState<TerminalPayload | null>(null);
  const [events, setEvents] = useState<TerminalEvent[]>([]);
  const [outputTruncated, setOutputTruncated] = useState(false);
  const [program, setProgram] = useState("");
  const [argumentsText, setArgumentsText] = useState("");
  const [cwd, setCwd] = useState(".");
  const [timeoutSeconds, setTimeoutSeconds] = useState("600");
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollGeneration = useRef(0);
  const outputRef = useRef<HTMLPreElement>(null);
  const followTail = useRef(true);

  const applyPayload = useCallback((payload: TerminalPayload, replace = false) => {
    setTerminal(payload);
    setEvents((current) => (replace || payload.truncated ? payload.events : mergeEvents(current, payload.events)));
    setOutputTruncated((current) => (replace ? payload.truncated : current || payload.truncated));
  }, []);

  const startPolling = useCallback((terminalId: string, initialCursor: number) => {
    const generation = ++pollGeneration.current;
    void (async () => {
      let cursor = initialCursor;
      while (pollGeneration.current === generation) {
        try {
          const payload = await api.getTerminal(terminalId, cursor, 10);
          if (pollGeneration.current !== generation) return;
          applyPayload(payload);
          cursor = payload.next;
          if (payload.status !== "running") return;
        } catch (pollError) {
          if (pollGeneration.current === generation) setError(errorMessage(pollError));
          return;
        }
      }
    })();
  }, [applyPayload]);

  const refresh = useCallback(async () => {
    const generation = ++pollGeneration.current;
    setLoading(true);
    setError(null);
    try {
      const payload = await api.getTerminal(undefined, 0, 0);
      if (pollGeneration.current !== generation) return;
      applyPayload(payload, true);
      setLoading(false);
      if (payload.status === "running" && payload.terminal_id) {
        startPolling(payload.terminal_id, payload.next);
      }
    } catch (refreshError) {
      if (pollGeneration.current === generation) setError(errorMessage(refreshError));
    } finally {
      if (pollGeneration.current === generation) setLoading(false);
    }
  }, [applyPayload, startPolling]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
    return () => {
      pollGeneration.current += 1;
    };
  }, [refresh]);

  useEffect(() => {
    const output = outputRef.current;
    if (output && followTail.current) output.scrollTop = output.scrollHeight;
  }, [events]);

  const start = async (event: FormEvent) => {
    event.preventDefault();
    const executable = program.trim();
    const timeout = Number(timeoutSeconds);
    if (!executable) {
      setError("请输入程序名或可执行文件路径。");
      return;
    }
    if (!Number.isInteger(timeout) || timeout < 1 || timeout > 3600) {
      setError("timeout 必须是 1–3600 秒的整数。");
      return;
    }
    const argv = [executable, ...argumentsText.split(/\r?\n/).filter((item) => item.length > 0)];
    pollGeneration.current += 1;
    followTail.current = true;
    setBusy(true);
    setError(null);
    try {
      const payload = await api.startTerminal(argv, cwd.trim() || ".", timeout);
      applyPayload(payload, true);
      if (payload.terminal_id && payload.status === "running") startPolling(payload.terminal_id, payload.next);
    } catch (startError) {
      setError(errorMessage(startError));
    } finally {
      setBusy(false);
    }
  };

  const sendInput = async (event: FormEvent) => {
    event.preventDefault();
    if (!terminal?.terminal_id || !input) return;
    setBusy(true);
    setError(null);
    try {
      await api.writeTerminal(terminal.terminal_id, input);
      setInput("");
    } catch (inputError) {
      setError(errorMessage(inputError));
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    if (!terminal?.terminal_id) return;
    pollGeneration.current += 1;
    setBusy(true);
    setError(null);
    try {
      applyPayload(await api.stopTerminal(terminal.terminal_id), true);
    } catch (stopError) {
      setError(errorMessage(stopError));
    } finally {
      setBusy(false);
    }
  };

  const running = terminal?.status === "running";
  const hasProcess = Boolean(terminal?.terminal_id);

  return (
    <section className="terminal-view" aria-labelledby="terminal-heading">
      <div className="terminal-toolbar">
        <div>
          <h2 id="terminal-heading" className="workspace-section-title">Terminal</h2>
          <p className="overview-note">单进程、结构化 argv、line-mode stdin；不经过 shell。</p>
        </div>
        <div className="terminal-toolbar-actions">
          {terminal ? <span className="overview-tag" data-tone={running ? "ok" : undefined}>{STATUS_LABELS[terminal.status]}</span> : null}
          <button type="button" className="files-action" aria-label="刷新 Terminal" onClick={() => void refresh()} disabled={loading || busy}>
            <RefreshCw aria-hidden="true" /> 刷新
          </button>
          {running ? (
            <button type="button" className="files-action terminal-stop" onClick={() => void stop()} disabled={busy}>
              <Square aria-hidden="true" /> 停止
            </button>
          ) : null}
        </div>
      </div>

      {loading ? <p className="overview-note" role="status"><Orb state="connecting" /> 正在读取 Terminal 状态…</p> : null}
      {error ? <p className="overview-error" role="alert" data-payload>{error}</p> : null}

      {terminal && !terminal.enabled && !hasProcess ? (
        <div className="terminal-disabled" role="status">
          <p>Terminal 默认关闭。请在项目终端显式启用：</p>
          <code data-payload>agent config set terminal_enabled true --cwd &lt;workspace&gt;</code>
        </div>
      ) : null}

      {terminal?.enabled && !running ? (
        <form className="terminal-start-form" onSubmit={(event) => void start(event)}>
          <label>
            <span>程序</span>
            <input aria-label="Terminal 程序" value={program} onChange={(event) => setProgram(event.target.value)} placeholder="python" autoComplete="off" />
          </label>
          <label>
            <span>参数（每行一项）</span>
            <textarea aria-label="Terminal 参数" value={argumentsText} onChange={(event) => setArgumentsText(event.target.value)} placeholder={'-c\nprint("ready")'} />
          </label>
          <div className="terminal-start-row">
            <label>
              <span>相对 cwd</span>
              <input aria-label="Terminal cwd" value={cwd} onChange={(event) => setCwd(event.target.value)} />
            </label>
            <label>
              <span>timeout 秒</span>
              <input aria-label="Terminal timeout" type="number" min="1" max="3600" value={timeoutSeconds} onChange={(event) => setTimeoutSeconds(event.target.value)} />
            </label>
            <button type="submit" className="files-action primary" disabled={busy}>
              <Play aria-hidden="true" /> 启动
            </button>
          </div>
          <p className="overview-note">非默认命令需先配置 allowed_commands。不要在 stdin 中输入密钥。</p>
        </form>
      ) : null}

      {hasProcess ? (
        <>
          <div className="terminal-meta" data-payload>
            <span title={terminal?.argv.join(" ")}>{terminal?.argv.join(" ")}</span>
            <span>cwd {terminal?.cwd}</span>
            <span>exit {terminal?.exit_code ?? "—"}</span>
          </div>
          {outputTruncated ? <p className="overview-tag" data-tone="warning">较早输出已截断</p> : null}
          {terminal?.cleanup_error ? <p className="overview-error" role="alert" data-payload>{terminal.cleanup_error}</p> : null}
          <pre
            ref={outputRef}
            className="terminal-output"
            aria-label="Terminal 输出"
            data-payload
            onScroll={(event) => {
              const element = event.currentTarget;
              followTail.current = element.scrollHeight - element.scrollTop - element.clientHeight < 28;
            }}
          >
            {events.length ? events.map((event) => (
              <span key={event.sequence} className="terminal-event" data-stream={event.stream}>{event.text}</span>
            )) : "等待输出…\n"}
          </pre>
        </>
      ) : null}

      {running ? (
        <form className="terminal-input-row" onSubmit={(event) => void sendInput(event)}>
          <input aria-label="Terminal stdin" value={input} onChange={(event) => setInput(event.target.value)} placeholder="发送一行到 stdin" autoComplete="off" />
          <button type="submit" className="files-action primary" disabled={busy || !input}>
            <Send aria-hidden="true" /> 发送
          </button>
        </form>
      ) : null}
    </section>
  );
}
