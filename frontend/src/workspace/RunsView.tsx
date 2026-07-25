import { useCallback, useMemo, useState, type ReactNode } from "react";
import { Copy, GitCompare, RotateCcw } from "lucide-react";

import { api } from "../api/client";
import type { DiffPayload, RunDetailPayload, RunListItem, RunSnapshot } from "../api/types";

interface RunsViewProps {
  runs: RunListItem[];
  onGlobalRefresh: () => void | Promise<void>;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败。";
}

function copyText(value: string): void {
  void navigator.clipboard?.writeText(value);
}

export function RunsView({ runs, onGlobalRefresh }: RunsViewProps) {
  const [statusFilter, setStatusFilter] = useState("");
  const [riskFilter, setRiskFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetailPayload | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [replayFilter, setReplayFilter] = useState("");
  const [replayTerminal, setReplayTerminal] = useState<"all" | "terminal">("all");
  const [diff, setDiff] = useState<DiffPayload | null>(null);
  const [diffError, setDiffError] = useState<string | null>(null);
  const [restoreTarget, setRestoreTarget] = useState<RunSnapshot | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [restoreResult, setRestoreResult] = useState<string | null>(null);

  const openRun = useCallback(async (runId: string) => {
    setSelectedId(runId);
    setDetailError(null);
    setDiff(null);
    setDiffError(null);
    setRestoreResult(null);
    setRestoreError(null);
    try {
      setDetail(await api.getRun(runId));
    } catch (error) {
      setDetail(null);
      setDetailError(errorMessage(error));
    }
  }, []);

  const showDiff = useCallback(async (snapshot: RunSnapshot) => {
    setDiffError(null);
    try {
      setDiff(await api.getDiff(snapshot.path, snapshot.snapshot_path));
    } catch (error) {
      setDiff(null);
      setDiffError(errorMessage(error));
    }
  }, []);

  const doRestore = useCallback(async () => {
    if (!restoreTarget || !selectedId) return;
    setRestoring(true);
    setRestoreError(null);
    try {
      const result = await api.restoreSnapshot(restoreTarget.path, restoreTarget.snapshot_path);
      setRestoreTarget(null);
      // openRun clears restoreResult on entry, so set the banner after the refresh.
      await openRun(selectedId);
      setRestoreResult(`${result.action}: ${result.path}`);
      void onGlobalRefresh();
    } catch (error) {
      setRestoreError(errorMessage(error));
    } finally {
      setRestoring(false);
    }
  }, [restoreTarget, selectedId, openRun, onGlobalRefresh]);

  const statuses = useMemo(() => Array.from(new Set(runs.map((run) => run.status))), [runs]);
  const risks = useMemo(() => Array.from(new Set(runs.map((run) => run.risk_level))), [runs]);
  const filteredRuns = useMemo(
    () =>
      runs.filter(
        (run) => (!statusFilter || run.status === statusFilter) && (!riskFilter || run.risk_level === riskFilter),
      ),
    [runs, statusFilter, riskFilter],
  );

  const filteredSteps = useMemo(() => {
    if (!detail) return [];
    const needle = replayFilter.trim().toLowerCase();
    return detail.replay.steps.filter(
      (step) =>
        (replayTerminal === "all" || step.terminal) &&
        (!needle || `${step.action} ${step.summary}`.toLowerCase().includes(needle)),
    );
  }, [detail, replayFilter, replayTerminal]);

  return (
    <section className="runs-view" aria-labelledby="runs-heading">
      <h2 id="runs-heading" className="sr-only">Runs</h2>
      <div className="runs-layout">
        <div className="runs-index-track">
          <div className="runs-filters">
            <label className="runs-filter">
              <span className="sr-only">状态过滤</span>
              <select aria-label="状态过滤" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="">全部状态</option>
                {statuses.map((status) => (
                  <option key={status} value={status}>{status}</option>
                ))}
              </select>
            </label>
            <label className="runs-filter">
              <span className="sr-only">风险过滤</span>
              <select aria-label="风险过滤" value={riskFilter} onChange={(event) => setRiskFilter(event.target.value)}>
                <option value="">全部风险</option>
                {risks.map((risk) => (
                  <option key={risk} value={risk}>{risk}</option>
                ))}
              </select>
            </label>
          </div>
          {filteredRuns.length === 0 ? (
            <p className="overview-note">无匹配运行记录。</p>
          ) : (
            <ul className="runs-index">
              {filteredRuns.map((run) => (
                <li key={run.run_id}>
                  <button
                    type="button"
                    className="runs-index-item runs-index-button"
                    aria-label={run.run_id}
                    aria-current={selectedId === run.run_id || undefined}
                    onClick={() => void openRun(run.run_id)}
                  >
                    <span className="runs-index-id">{run.run_id}</span>
                    <span className="overview-tag" data-tone={run.risk_level === "low" ? "ok" : "warning"}>{run.risk_level}</span>
                    <span className="runs-index-status">{run.status}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="runs-detail">
          {detailError ? (
            <div className="files-error" role="alert">
              <p>无法加载运行详情。</p>
              <p className="overview-error" data-payload>{detailError}</p>
            </div>
          ) : !detail ? (
            <p className="overview-note">选择左侧运行以查看详情。</p>
          ) : (
            <div className="runs-detail-body">
              <RunSection title="Summary">
                <pre className="runs-pre" data-payload>{detail.summary}</pre>
              </RunSection>

              <RunSection title="Task Review">
                <KeyRow label="最近动作" value={detail.review.latest_action} />
                <KeyRow label="最后观察" value={detail.review.last_observation_summary} />
                <LabeledList label="变更文件" items={detail.review.changed_files} empty="无变更文件。" />
                <LabeledList label="人工检查" items={detail.review.manual_checks} />
              </RunSection>

              <RunSection title="Workflow">
                <CommandList commands={detail.workflow.verification_commands} />
                <LabeledList label="步骤" items={detail.workflow.review_steps} />
              </RunSection>

              <RunSection title="Failure">
                <KeyRow label="状态" value={detail.failure.status} />
                <KeyRow label="失败数" value={String(detail.failure.failure_count)} />
                <LabeledList label="下一步检查" items={detail.failure.next_checks} />
              </RunSection>

              <RunSection title="Patch Review">
                <p className="overview-tag" data-tone={detail.patch_review.risk_level === "low" ? "ok" : "warning"}>
                  {detail.patch_review.risk_level}
                </p>
                <p className="overview-note" data-payload>{detail.patch_review.summary}</p>
                <LabeledList label="检查" items={detail.patch_review.checks} />
                <KeyRow label="下一步" value={detail.patch_review.next_action} />
              </RunSection>

              <RunSection title="Recovery">
                <KeyRow label="状态" value={detail.recovery.status} />
                <KeyRow label="可回滚" value={detail.recovery.rollback_available ? "是" : "否"} />
                <p className="overview-note" data-payload>{detail.recovery.summary}</p>
                <LabeledList label="步骤" items={detail.recovery.steps} />
                <KeyRow label="下一步" value={detail.recovery.next_action} />
              </RunSection>

              <RunSection title="Replay">
                <div className="replay-controls">
                  <span className="overview-tag" data-tone="ok">只读</span>
                  <input
                    type="text"
                    className="replay-filter"
                    aria-label="过滤 replay"
                    placeholder="过滤 replay"
                    value={replayFilter}
                    onChange={(event) => setReplayFilter(event.target.value)}
                  />
                  <label className="runs-filter">
                    <span className="sr-only">终态过滤</span>
                    <select aria-label="终态过滤" value={replayTerminal} onChange={(event) => setReplayTerminal(event.target.value as "all" | "terminal")}>
                      <option value="all">全部</option>
                      <option value="terminal">终态</option>
                    </select>
                  </label>
                </div>
                {filteredSteps.length === 0 ? (
                  <p className="overview-note">无匹配步骤。</p>
                ) : (
                  <ol className="replay-steps">
                    {filteredSteps.map((step) => (
                      <li key={step.line_number} className="replay-step" data-payload>
                        <span className="replay-action">{step.action}</span>
                        <span className="overview-tag" data-tone={step.status === "ok" ? "ok" : "warning"}>{step.status}</span>
                        <span className="replay-summary">{step.summary}</span>
                        {step.terminal ? <span className="replay-terminal">terminal</span> : null}
                      </li>
                    ))}
                  </ol>
                )}
              </RunSection>

              <RunSection title="Snapshots">
                {detail.snapshots.length === 0 ? (
                  <p className="overview-note">无 snapshot。</p>
                ) : (
                  <ul className="snapshot-list">
                    {detail.snapshots.map((snapshot) => (
                      <li key={snapshot.snapshot_path} className="snapshot-item" data-payload>
                        <span className="snapshot-path">{snapshot.path}</span>
                        <span className="snapshot-src">{snapshot.snapshot_path}</span>
                        <button type="button" className="files-action" onClick={() => void showDiff(snapshot)}>
                          <GitCompare aria-hidden="true" /> 查看 diff
                        </button>
                        <button type="button" className="files-action" onClick={() => setRestoreTarget(snapshot)}>
                          <RotateCcw aria-hidden="true" /> 恢复
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {restoreResult ? <p className="files-saved" data-payload>已恢复 · {restoreResult}</p> : null}
              </RunSection>

              {diffError ? <p className="overview-error" data-payload>{diffError}</p> : null}
              {diff ? (
                <RunSection title="Diff">
                  <div className="diff-status">
                    {diff.truncated ? <span className="overview-tag" data-tone="warning">已截断</span> : null}
                    {diff.snapshot_missing ? <span className="overview-tag" data-tone="warning">snapshot 缺失</span> : null}
                    {!diff.current_exists ? <span className="overview-tag" data-tone="warning">当前文件不存在</span> : null}
                    <button type="button" className="files-action" onClick={() => copyText(diff.diff)}>
                      <Copy aria-hidden="true" /> 复制 diff
                    </button>
                  </div>
                  <pre className="runs-pre diff-body" data-payload>{diff.diff || "（无差异）"}</pre>
                </RunSection>
              ) : null}

              <RunSection title="Trace">
                <ol className="trace-list">
                  {detail.tool_calls.map((call) => (
                    <li key={call.line_number} className="trace-item" data-payload>
                      <span className="trace-line">#{call.line_number}</span>
                      <span className="overview-tag" data-tone={call.valid ? "ok" : "warning"}>{call.valid ? "valid" : "invalid"}</span>
                      {call.error ? <span className="trace-error">{call.error}</span> : null}
                    </li>
                  ))}
                </ol>
              </RunSection>
            </div>
          )}
        </div>
      </div>

      {restoreTarget ? (
        <div className="files-confirm" role="dialog" aria-label="确认恢复">
          <p>
            即将从 snapshot <strong data-payload>{restoreTarget.snapshot_path}</strong> 恢复
            <strong data-payload>{restoreTarget.path}</strong>。
          </p>
          <p className="overview-note">结果可能是恢复旧内容，也可能删除由该 run 新建的文件。</p>
          {restoreError ? <p className="overview-error" data-payload>{restoreError}</p> : null}
          <div className="files-confirm-actions">
            <button type="button" className="files-action primary" disabled={restoring} onClick={() => void doRestore()}>
              确认恢复
            </button>
            <button type="button" className="files-action" disabled={restoring} onClick={() => setRestoreTarget(null)}>
              取消
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function RunSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="run-section" aria-labelledby={`run-section-${title}`}>
      <h3 id={`run-section-${title}`} className="run-section-title">{title}</h3>
      {children}
    </section>
  );
}

function KeyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="run-key-row">
      <span className="run-key">{label}</span>
      <span className="run-value" data-payload>{value}</span>
    </div>
  );
}

function LabeledList({ label, items, empty }: { label: string; items: string[]; empty?: string }) {
  return (
    <div className="run-list-block">
      <span className="run-key">{label}</span>
      {items.length === 0 ? (
        <span className="overview-note">{empty ?? "无。"}</span>
      ) : (
        <ul className="run-plain-list">
          {items.map((item, index) => (
            <li key={`${item}-${index}`} data-payload>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CommandList({ commands }: { commands: string[] }) {
  return (
    <div className="run-list-block">
      <span className="run-key">验证命令</span>
      <ul className="command-list">
        {commands.map((command, index) => (
          <li key={`${command}-${index}`} className="command-row">
            <code className="command-text" data-payload>{command}</code>
            <button type="button" className="files-action" aria-label={`复制 ${command}`} onClick={() => copyText(command)}>
              <Copy aria-hidden="true" /> 复制
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
