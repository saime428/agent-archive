import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState } from "react";
import { ArrowLeft, FileText, FolderTree, Pencil, Save, Search } from "lucide-react";

import { api } from "../api/client";
import type { FilesPayload } from "../api/types";
import { ConfirmDialog } from "./ConfirmDialog";

// Lets WorkspacePanel query the edit buffer state before closing or switching tabs.
export interface FilesViewHandle {
  isDirty: () => boolean;
}

interface OpenFile {
  path: string;
  content: string;
  truncated: boolean;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败。";
}

function parentPath(path: string): string | null {
  if (path === "." || path === "") return null;
  const index = path.lastIndexOf("/");
  return index === -1 ? "." : path.slice(0, index);
}

function byteLength(text: string): number {
  return new TextEncoder().encode(text).length;
}

export const FilesView = forwardRef<FilesViewHandle>(function FilesView(_props, ref) {
  const [dirPath, setDirPath] = useState(".");
  const [entries, setEntries] = useState<FilesPayload["entries"]>([]);
  const [dirError, setDirError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<OpenFile | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [mode, setMode] = useState<"preview" | "edit">("preview");
  const [buffer, setBuffer] = useState("");
  const [baseline, setBaseline] = useState("");
  const [saveConfirm, setSaveConfirm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedRun, setSavedRun] = useState<string | null>(null);
  const [discard, setDiscard] = useState<{ run: () => void } | null>(null);

  const dirty = mode === "edit" && buffer !== baseline;
  const hasReplacement = selected ? selected.content.includes("�") : false;
  const readOnly = selected ? selected.truncated || hasReplacement : false;

  useImperativeHandle(ref, () => ({ isDirty: () => dirty }), [dirty]);

  const loadDir = useCallback(async (path: string) => {
    try {
      const payload = await api.listFiles(path === "." ? undefined : path);
      setEntries(payload.entries);
      setDirPath(payload.path);
      setDirError(null);
    } catch (error) {
      setDirError(errorMessage(error));
    }
  }, []);

  useEffect(() => {
    void loadDir(".");
  }, [loadDir]);

  const openFile = useCallback(async (path: string) => {
    setFileError(null);
    setSaveError(null);
    setSavedRun(null);
    try {
      const payload = await api.getFile(path);
      setSelected({ path: payload.path, content: payload.content, truncated: payload.truncated });
      setBaseline(payload.content);
      setBuffer(payload.content);
      setMode("preview");
    } catch (error) {
      setSelected(null);
      setFileError(errorMessage(error));
    }
  }, []);

  // Any navigation away from a dirty edit buffer is gated by an explicit discard choice.
  const guard = useCallback(
    (run: () => void) => {
      if (dirty) setDiscard({ run });
      else run();
    },
    [dirty],
  );

  const doSave = useCallback(async () => {
    if (!selected) return;
    setSaving(true);
    setSaveError(null);
    try {
      const result = await api.saveFile(selected.path, buffer);
      setBaseline(buffer);
      setSelected({ ...selected, content: buffer });
      setMode("preview");
      setSavedRun(result.run_id);
      setSaveConfirm(false);
    } catch (error) {
      setSaveError(errorMessage(error));
    } finally {
      setSaving(false);
    }
  }, [selected, buffer]);

  const visibleEntries = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return needle ? entries.filter((entry) => entry.name.toLowerCase().includes(needle)) : entries;
  }, [entries, filter]);

  const parent = parentPath(dirPath);

  return (
    <section className="files-view" aria-labelledby="files-heading">
      <h2 id="files-heading" className="sr-only">Files</h2>
      <div className="files-layout">
        <div className="files-track">
          <div className="files-path" data-payload>{dirPath}</div>
          <div className="files-controls">
            {parent !== null ? (
              <button type="button" className="files-up" onClick={() => guard(() => void loadDir(parent))}>
                <ArrowLeft aria-hidden="true" /> 返回上级
              </button>
            ) : null}
            <label className="files-search">
              <Search aria-hidden="true" />
              <span className="sr-only">过滤当前目录</span>
              <input
                type="text"
                value={filter}
                placeholder="过滤当前目录"
                onChange={(event) => setFilter(event.target.value)}
              />
            </label>
          </div>
          {dirError ? <p className="overview-error">{dirError}</p> : null}
          <ul className="files-entries">
            {visibleEntries.map((entry) => (
              <li key={entry.path}>
                <button
                  type="button"
                  className="files-entry"
                  data-kind={entry.kind}
                  aria-label={entry.name}
                  aria-current={selected?.path === entry.path || undefined}
                  onClick={() =>
                    guard(() => (entry.kind === "dir" ? void loadDir(entry.path) : void openFile(entry.path)))
                  }
                >
                  {entry.kind === "dir" ? <FolderTree aria-hidden="true" /> : <FileText aria-hidden="true" />}
                  <span className="files-entry-name" title={entry.path}>{entry.name}</span>
                  {entry.size !== null ? <span className="files-entry-size">{entry.size}</span> : null}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="files-detail">
          {fileError ? (
            <div className="files-error" role="alert">
              <p>无法打开文件。</p>
              <p className="overview-error" data-payload>{fileError}</p>
            </div>
          ) : !selected ? (
            <p className="overview-note">选择左侧文件以预览。</p>
          ) : (
            <>
              <div className="files-detail-head">
                <span className="files-detail-path" data-payload>{selected.path}</span>
                {selected.truncated ? <span className="overview-tag" data-tone="warning">文件已截断，仅供预览</span> : null}
                {hasReplacement && !selected.truncated ? (
                  <span className="overview-tag" data-tone="warning">包含替换字符，可能编码损坏，仅供预览</span>
                ) : null}
                {!readOnly && mode === "preview" ? (
                  <button type="button" className="files-action" onClick={() => setMode("edit")}>
                    <Pencil aria-hidden="true" /> 编辑
                  </button>
                ) : null}
                {!readOnly && mode === "edit" ? (
                  <button type="button" className="files-action" disabled={!dirty} onClick={() => setSaveConfirm(true)}>
                    <Save aria-hidden="true" /> 保存
                  </button>
                ) : null}
              </div>

              {savedRun ? <p className="files-saved" data-payload>已保存 · run {savedRun}</p> : null}
              {saveError ? <p className="overview-error" data-payload>{saveError}</p> : null}

              {mode === "edit" ? (
                <textarea
                  className="files-editor"
                  aria-label="文件编辑器"
                  spellCheck={false}
                  value={buffer}
                  data-payload
                  onChange={(event) => setBuffer(event.target.value)}
                />
              ) : (
                <pre className="files-preview" data-payload>{selected.content}</pre>
              )}
            </>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={saveConfirm && selected !== null}
        title="确认保存"
        onOpenChange={(next) => !next && setSaveConfirm(false)}
        confirmLabel="确认保存"
        cancelLabel="取消"
        confirmDisabled={saving}
        onConfirm={() => void doSave()}
      >
        {selected ? (
          <p>
            即将保存 <strong data-payload>{selected.path}</strong>（{byteLength(buffer)} 字节，UTF-8），
            <strong>将创建 snapshot</strong> 后写入。
          </p>
        ) : null}
      </ConfirmDialog>

      <ConfirmDialog
        open={discard !== null}
        title="未保存修改"
        onOpenChange={(next) => !next && setDiscard(null)}
        confirmLabel="丢弃修改"
        cancelLabel="继续编辑"
        onConfirm={() => {
          const run = discard?.run;
          setDiscard(null);
          setMode("preview");
          setBuffer(baseline);
          run?.();
        }}
      >
        <p>当前文件有未保存修改。丢弃修改并继续？</p>
      </ConfirmDialog>
    </section>
  );
});
