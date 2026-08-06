import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";

import { api } from "../api/client";
import type { GitDiffPayload, GitStatusEntry, GitStatusPayload } from "../api/types";
import { Orb } from "../Orb";

type GitArea = "staged" | "unstaged";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败。";
}

function unavailableMessage(reason: GitStatusPayload["reason"]): string {
  if (reason === "git_unavailable") return "未找到 Git 可执行文件。";
  if (reason === "repository_root_outside_workspace") return "请将工作区打开到 Git 仓库根目录。";
  return "当前工作区不是 Git 仓库。";
}

function entryBadges(entry: GitStatusEntry) {
  const badges: Array<{ label: string; kind: string }> = [];
  if (entry.conflicted) badges.push({ label: "conflict", kind: "conflict" });
  if (entry.staged) badges.push({ label: "staged", kind: "staged" });
  if (entry.unstaged) badges.push({ label: "unstaged", kind: "unstaged" });
  if (entry.untracked) badges.push({ label: "untracked", kind: "untracked" });
  return badges;
}

export function GitView() {
  const [status, setStatus] = useState<GitStatusPayload | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [area, setArea] = useState<GitArea>("unstaged");
  const [diff, setDiff] = useState<GitDiffPayload | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState<string | null>(null);
  const statusSequence = useRef(0);
  const diffSequence = useRef(0);

  const loadStatus = useCallback(async () => {
    const sequence = ++statusSequence.current;
    diffSequence.current += 1;
    setStatusLoading(true);
    setStatusError(null);
    setSelectedPath(null);
    setDiff(null);
    setDiffError(null);
    setDiffLoading(false);
    try {
      const payload = await api.getGitStatus();
      if (sequence === statusSequence.current) setStatus(payload);
    } catch (error) {
      if (sequence === statusSequence.current) {
        setStatus(null);
        setStatusError(errorMessage(error));
      }
    } finally {
      if (sequence === statusSequence.current) setStatusLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadStatus();
    return () => {
      statusSequence.current += 1;
      diffSequence.current += 1;
    };
  }, [loadStatus]);

  const selected = useMemo(
    () => status?.entries.find((entry) => entry.path === selectedPath) ?? null,
    [selectedPath, status],
  );

  const loadDiff = async (entry: GitStatusEntry, nextArea: GitArea) => {
    const sequence = ++diffSequence.current;
    setSelectedPath(entry.path);
    setArea(nextArea);
    setDiff(null);
    setDiffError(null);
    if (entry.untracked) {
      setDiffLoading(false);
      return;
    }
    setDiffLoading(true);
    try {
      const payload = await api.getGitDiff(entry.path, nextArea);
      if (sequence === diffSequence.current) setDiff(payload);
    } catch (error) {
      if (sequence === diffSequence.current) setDiffError(errorMessage(error));
    } finally {
      if (sequence === diffSequence.current) setDiffLoading(false);
    }
  };

  const selectEntry = (entry: GitStatusEntry) => {
    void loadDiff(entry, entry.unstaged ? "unstaged" : "staged");
  };

  return (
    <section className="git-view" aria-labelledby="git-heading">
      <div className="git-toolbar">
        <div>
          <h2 id="git-heading" className="workspace-section-title">Git changes</h2>
          <p className="overview-note">只读查看当前仓库的 staged、unstaged 与 untracked 变化。</p>
        </div>
        <button
          type="button"
          className="files-action"
          aria-label="刷新 Git 状态"
          disabled={statusLoading}
          onClick={() => void loadStatus()}
        >
          <RefreshCw aria-hidden="true" /> 刷新
        </button>
      </div>

      <div className="git-status" aria-live="polite">
        {statusLoading ? <p className="overview-note" role="status"><Orb state="searching" /> 正在读取 Git 状态…</p> : null}
        {statusError ? <p className="overview-error" role="alert" data-payload>{statusError}</p> : null}
        {status?.is_repository && status.truncated ? (
          <p className="overview-note">状态项至少 {status.entry_count} 条，仅显示前 {status.entry_count} 条。</p>
        ) : null}
      </div>

      {status && !status.is_repository ? (
        <p className="overview-note" role="status">{unavailableMessage(status.reason)}</p>
      ) : null}
      {status?.is_repository && !statusLoading && status.entries.length === 0 ? (
        <p className="overview-note" role="status">工作区干净。</p>
      ) : null}

      {status?.is_repository && status.entries.length ? (
        <div className="git-layout">
          <div className="git-track">
            <ul className="git-entries" aria-label="Git 变化文件">
              {status.entries.map((entry) => {
                const badges = entryBadges(entry);
                return (
                  <li key={entry.path}>
                    <button
                      type="button"
                      className="git-entry"
                      aria-current={selectedPath === entry.path || undefined}
                      aria-label={`${entry.path} ${badges.map((badge) => badge.label).join(" ")}`}
                      onClick={() => selectEntry(entry)}
                    >
                      <span className="git-entry-path" title={entry.path} data-payload>{entry.path}</span>
                      {entry.original_path ? (
                        <span className="git-entry-original" title={entry.original_path} data-payload>
                          ← {entry.original_path}
                        </span>
                      ) : null}
                      <span className="git-badges" aria-hidden="true">
                        {badges.map((badge) => (
                          <span key={badge.kind} className="git-badge" data-kind={badge.kind}>{badge.label}</span>
                        ))}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>

          <div className="git-detail">
            {!selected ? <p className="overview-note">选择左侧文件以查看差异。</p> : (
              <>
                <div className="git-detail-head">
                  <span className="git-detail-path" title={selected.path} data-payload>{selected.path}</span>
                  {!selected.untracked ? (
                    <div className="git-area-tabs" aria-label="Git diff 区域">
                      {selected.unstaged ? (
                        <button
                          type="button"
                          className="workspace-tab"
                          aria-pressed={area === "unstaged"}
                          onClick={() => void loadDiff(selected, "unstaged")}
                        >
                          Unstaged
                        </button>
                      ) : null}
                      {selected.staged ? (
                        <button
                          type="button"
                          className="workspace-tab"
                          aria-pressed={area === "staged"}
                          onClick={() => void loadDiff(selected, "staged")}
                        >
                          Staged
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                </div>

                {selected.untracked ? (
                  <p className="overview-note">Untracked 文件没有 Git diff；请到 Files 中查看内容。</p>
                ) : null}
                {diffLoading ? <p className="overview-note" role="status"><Orb state="searching" /> 正在读取 {area} diff…</p> : null}
                {diffError ? <p className="overview-error" role="alert" data-payload>{diffError}</p> : null}
                {diff?.truncated ? <p className="overview-tag" data-tone="warning">Diff 已截断</p> : null}
                {diff && !diff.diff ? <p className="overview-note">该区域没有可显示的差异。</p> : null}
                {diff?.diff ? <pre className="git-diff" data-payload>{diff.diff}</pre> : null}
              </>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}
