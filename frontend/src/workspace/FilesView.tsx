import {
  Suspense,
  forwardRef,
  lazy,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { ArrowLeft, FileText, FolderTree, Pencil, Save, Search, X } from "lucide-react";

import { api } from "../api/client";
import type { FilesPayload, SearchPayload } from "../api/types";
import { useTheme } from "../theme";
import { ConfirmDialog } from "./ConfirmDialog";
import { Orb } from "../Orb";

const MonacoEditor = lazy(() => import("./MonacoEditor"));
const MAX_OPEN_TABS = 20;
const DESKTOP_EDITOR_QUERY = "(min-width: 768px)";

export interface FilesViewHandle {
  isDirty: () => boolean;
}

interface OpenFile {
  path: string;
  buffer: string;
  baseline: string;
  truncated: boolean;
  editing: boolean;
  savedRun: string | null;
}

interface JumpTarget {
  path: string;
  line: number;
  key: number;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败。";
}

function parentPath(path: string): string | null {
  if (path === "." || path === "") return null;
  const index = path.lastIndexOf("/");
  return index === -1 ? "." : path.slice(0, index);
}

function fileName(path: string): string {
  return path.split("/").at(-1) ?? path;
}

function byteLength(text: string): number {
  return new TextEncoder().encode(text).length;
}

function isReadOnly(file: OpenFile): boolean {
  return file.truncated || file.buffer.includes("�");
}

function useDesktopEditor(): boolean {
  const [desktop, setDesktop] = useState(() => window.matchMedia(DESKTOP_EDITOR_QUERY).matches);
  useEffect(() => {
    const media = window.matchMedia(DESKTOP_EDITOR_QUERY);
    const update = () => setDesktop(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return desktop;
}

function NativeEditor({
  value,
  readOnly,
  jumpLine,
  jumpKey,
  onChange,
  onSave,
}: {
  value: string;
  readOnly: boolean;
  jumpLine: number | null;
  jumpKey: number;
  onChange: (value: string) => void;
  onSave: () => void;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!ref.current || jumpLine === null) return;
    const lines = value.split("\n");
    const line = Math.min(Math.max(jumpLine, 1), lines.length);
    const offset = lines.slice(0, line - 1).reduce((total, item) => total + item.length + 1, 0);
    ref.current.focus();
    ref.current.setSelectionRange(offset, offset);
  }, [jumpKey, jumpLine, value]);

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "s") return;
    event.preventDefault();
    if (!readOnly) onSave();
  };

  return (
    <textarea
      ref={ref}
      className="files-editor files-editor-native"
      aria-label="文件编辑器"
      spellCheck={false}
      readOnly={readOnly}
      value={value}
      data-payload
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={handleKeyDown}
    />
  );
}

export const FilesView = forwardRef<FilesViewHandle>(function FilesView(_props, ref) {
  const { resolvedMode } = useTheme();
  const desktopEditor = useDesktopEditor();
  const [dirPath, setDirPath] = useState(".");
  const [entries, setEntries] = useState<FilesPayload["entries"]>([]);
  const [dirError, setDirError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [tabs, setTabs] = useState<OpenFile[]>([]);
  const [activePath, setActivePath] = useState<string | null>(null);
  const [openingPath, setOpeningPath] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [saveConfirm, setSaveConfirm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [discardPath, setDiscardPath] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [searchResult, setSearchResult] = useState<SearchPayload | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [jump, setJump] = useState<JumpTarget | null>(null);
  const openSequence = useRef(0);
  const searchSequence = useRef(0);

  const selected = useMemo(() => tabs.find((tab) => tab.path === activePath) ?? null, [activePath, tabs]);
  const dirty = tabs.some((tab) => tab.editing && tab.buffer !== tab.baseline);
  const selectedDirty = Boolean(selected?.editing && selected.buffer !== selected.baseline);
  const selectedReadOnly = selected ? isReadOnly(selected) : true;

  useImperativeHandle(ref, () => ({ isDirty: () => dirty }), [dirty]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

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
    // loadDir only updates state after its awaited request resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadDir(".");
  }, [loadDir]);

  const activateTab = (path: string) => {
    setActivePath(path);
    setJump(null);
    setFileError(null);
    setSaveError(null);
  };

  const openFile = useCallback(
    async (path: string, line: number | null = null) => {
      setFileError(null);
      setSaveError(null);
      const existing = tabs.find((tab) => tab.path === path);
      if (existing) {
        setActivePath(path);
        setJump(line === null ? null : { path, line, key: Date.now() });
        return;
      }
      if (tabs.length >= MAX_OPEN_TABS) {
        setFileError(`最多只能同时打开 ${MAX_OPEN_TABS} 个文件。`);
        return;
      }

      const sequence = ++openSequence.current;
      setOpeningPath(path);
      try {
        const payload = await api.getFile(path);
        const opened: OpenFile = {
          path: payload.path,
          buffer: payload.content,
          baseline: payload.content,
          truncated: payload.truncated,
          editing: false,
          savedRun: null,
        };
        setTabs((current) => (current.some((tab) => tab.path === opened.path) ? current : [...current, opened]));
        if (sequence === openSequence.current) {
          setActivePath(opened.path);
          setJump(line === null ? null : { path: opened.path, line, key: Date.now() });
        }
      } catch (error) {
        if (sequence === openSequence.current) setFileError(errorMessage(error));
      } finally {
        if (sequence === openSequence.current) setOpeningPath(null);
      }
    },
    [tabs],
  );

  const updateTab = useCallback((path: string, update: (tab: OpenFile) => OpenFile) => {
    setTabs((current) => current.map((tab) => (tab.path === path ? update(tab) : tab)));
  }, []);

  const closeTab = (path: string) => {
    const index = tabs.findIndex((tab) => tab.path === path);
    if (index === -1) return;
    const next = tabs.filter((tab) => tab.path !== path);
    setTabs(next);
    if (activePath === path) setActivePath(next[Math.min(index, next.length - 1)]?.path ?? null);
    if (jump?.path === path) setJump(null);
  };

  const requestCloseTab = (path: string) => {
    const tab = tabs.find((item) => item.path === path);
    if (tab?.editing && tab.buffer !== tab.baseline) setDiscardPath(path);
    else closeTab(path);
  };

  const requestSave = useCallback(() => {
    if (selected && selected.editing && selected.buffer !== selected.baseline && !isReadOnly(selected)) {
      setSaveConfirm(true);
    }
  }, [selected]);

  const doSave = useCallback(async () => {
    if (!selected) return;
    const { path, buffer } = selected;
    setSaving(true);
    setSaveError(null);
    try {
      const result = await api.saveFile(path, buffer);
      updateTab(path, (tab) => ({ ...tab, baseline: buffer, editing: false, savedRun: result.run_id }));
      setSaveConfirm(false);
    } catch (error) {
      setSaveError(errorMessage(error));
      setSaveConfirm(false);
    } finally {
      setSaving(false);
    }
  }, [selected, updateTab]);

  const runSearch = async (event: FormEvent) => {
    event.preventDefault();
    const normalized = query.trim();
    if (!normalized) return;
    const sequence = ++searchSequence.current;
    setSearching(true);
    setSearchError(null);
    try {
      const result = await api.searchFiles(normalized);
      if (sequence === searchSequence.current) setSearchResult(result);
    } catch (error) {
      if (sequence === searchSequence.current) {
        setSearchResult(null);
        setSearchError(errorMessage(error));
      }
    } finally {
      if (sequence === searchSequence.current) setSearching(false);
    }
  };

  const visibleEntries = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return needle ? entries.filter((entry) => entry.name.toLowerCase().includes(needle)) : entries;
  }, [entries, filter]);

  const parent = parentPath(dirPath);
  const jumpLine = jump && jump.path === selected?.path ? jump.line : null;

  return (
    <section className="files-view" aria-labelledby="files-heading">
      <h2 id="files-heading" className="sr-only">Files</h2>
      <div className="files-layout">
        <div className="files-track">
          <div className="files-path" data-payload>{dirPath}</div>
          <div className="files-controls">
            {parent !== null ? (
              <button type="button" className="files-up" onClick={() => void loadDir(parent)}>
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
                  aria-current={activePath === entry.path || undefined}
                  onClick={() => (entry.kind === "dir" ? void loadDir(entry.path) : void openFile(entry.path))}
                >
                  {entry.kind === "dir" ? <FolderTree aria-hidden="true" /> : <FileText aria-hidden="true" />}
                  <span className="files-entry-name" title={entry.path}>{entry.name}</span>
                  {entry.size !== null ? <span className="files-entry-size">{entry.size}</span> : null}
                </button>
              </li>
            ))}
          </ul>

          <form className="workspace-search" role="search" onSubmit={(event) => void runSearch(event)}>
            <label className="files-search">
              <Search aria-hidden="true" />
              <span className="sr-only">递归搜索工作区</span>
              <input
                type="search"
                aria-label="递归搜索工作区"
                value={query}
                maxLength={200}
                placeholder="搜索文本或 *.py"
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            <button type="submit" className="files-action" disabled={searching || !query.trim()}>
              {searching ? "搜索中" : "搜索"}
            </button>
          </form>
          <div className="workspace-search-status" aria-live="polite">
            {searchError ? <p className="overview-error" data-payload>{searchError}</p> : null}
            {searchResult ? (
              searchResult.matches.length === 0 ? (
                <p className="overview-note">未找到匹配项。</p>
              ) : (
                <>
                  <p className="overview-note">
                    已扫描 {searchResult.scanned_files} 个文件，结果
                    {searchResult.scan_truncated ? "至少 " : " "}{searchResult.total_matches} 条
                    {searchResult.truncated ? `，仅显示前 ${searchResult.matches.length} 条` : ""}
                    {searchResult.skipped_files ? `，跳过 ${searchResult.skipped_files} 个文件` : ""}。
                  </p>
                  <ul className="files-search-results">
                    {searchResult.matches.map((match, index) => (
                      <li key={`${match.path}:${match.line ?? "path"}:${index}`}>
                        <button
                          type="button"
                          className="files-search-result"
                          aria-label={`${match.path}${match.line === null ? "" : ` 第 ${match.line} 行`}`}
                          onClick={() => void openFile(match.path, match.line)}
                        >
                          <span className="files-search-result-path" title={match.path}>{match.path}</span>
                          {match.line !== null ? <span className="files-search-result-line">L{match.line}</span> : null}
                          {match.excerpt !== null ? <code data-payload>{match.excerpt}</code> : null}
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )
            ) : null}
          </div>
        </div>

        <div className="files-detail">
          {tabs.length ? (
            <div className="files-tabs" role="tablist" aria-label="打开的文件">
              {tabs.map((tab) => {
                const tabDirty = tab.editing && tab.buffer !== tab.baseline;
                return (
                  <div className="files-tab-wrap" key={tab.path} data-active={tab.path === activePath || undefined}>
                    <button
                      type="button"
                      role="tab"
                      className="files-tab"
                      aria-label={fileName(tab.path)}
                      aria-selected={tab.path === activePath}
                      title={tab.path}
                      onClick={() => activateTab(tab.path)}
                    >
                      <span>{fileName(tab.path)}</span>
                      {tabDirty ? <span className="files-tab-dirty" aria-label="已修改">●</span> : null}
                    </button>
                    <button
                      type="button"
                      className="files-tab-close"
                      aria-label={`关闭 ${tab.path}`}
                      onClick={() => requestCloseTab(tab.path)}
                    >
                      <X aria-hidden="true" />
                    </button>
                  </div>
                );
              })}
            </div>
          ) : null}

          {fileError ? (
            <div className="files-error" role="alert">
              <p>无法打开文件。</p>
              <p className="overview-error" data-payload>{fileError}</p>
            </div>
          ) : null}
          {openingPath ? <p className="overview-note" role="status"><Orb state="searching" /> 正在打开 {openingPath}…</p> : null}

          {!selected ? (
            fileError ? null : <p className="overview-note">选择文件或搜索结果以打开。</p>
          ) : (
            <>
              <div className="files-detail-head">
                <span className="files-detail-path" data-payload>{selected.path}</span>
                {selected.truncated ? <span className="overview-tag" data-tone="warning">文件已截断，仅供预览</span> : null}
                {selected.buffer.includes("�") && !selected.truncated ? (
                  <span className="overview-tag" data-tone="warning">包含替换字符，可能编码损坏，仅供预览</span>
                ) : null}
                {!selectedReadOnly && !selected.editing ? (
                  <button
                    type="button"
                    className="files-action"
                    onClick={() => updateTab(selected.path, (tab) => ({ ...tab, editing: true }))}
                  >
                    <Pencil aria-hidden="true" /> 编辑
                  </button>
                ) : null}
                {!selectedReadOnly && selected.editing ? (
                  <button type="button" className="files-action" disabled={!selectedDirty} onClick={requestSave}>
                    <Save aria-hidden="true" /> 保存
                  </button>
                ) : null}
              </div>

              {selected.savedRun ? <p className="files-saved" data-payload>已保存 · run {selected.savedRun}</p> : null}
              {saveError ? <p className="overview-error" data-payload>{saveError}</p> : null}
              {jumpLine !== null ? <p className="files-jump-status">已跳转到第 {jumpLine} 行</p> : null}

              {desktopEditor ? (
                <Suspense fallback={<div className="files-editor-loading" role="status"><Orb state="working" /> 编辑器加载中…</div>}>
                  <MonacoEditor
                    path={selected.path}
                    value={selected.buffer}
                    openPaths={tabs.map((tab) => tab.path)}
                    readOnly={selectedReadOnly || !selected.editing}
                    mode={resolvedMode}
                    jumpLine={jumpLine}
                    jumpKey={jump?.key ?? 0}
                    onChange={(value) => updateTab(selected.path, (tab) => ({ ...tab, buffer: value, savedRun: null }))}
                    onSave={requestSave}
                  />
                </Suspense>
              ) : (
                <NativeEditor
                  value={selected.buffer}
                  readOnly={selectedReadOnly || !selected.editing}
                  jumpLine={jumpLine}
                  jumpKey={jump?.key ?? 0}
                  onChange={(value) => updateTab(selected.path, (tab) => ({ ...tab, buffer: value, savedRun: null }))}
                  onSave={requestSave}
                />
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
            即将保存 <strong data-payload>{selected.path}</strong>（{byteLength(selected.buffer)} 字节，UTF-8），
            <strong>将创建 snapshot</strong> 后写入。
          </p>
        ) : null}
      </ConfirmDialog>

      <ConfirmDialog
        open={discardPath !== null}
        title="未保存修改"
        onOpenChange={(next) => !next && setDiscardPath(null)}
        confirmLabel="丢弃修改"
        cancelLabel="继续编辑"
        onConfirm={() => {
          const path = discardPath;
          setDiscardPath(null);
          if (path) closeTab(path);
        }}
      >
        <p>该标签有未保存修改。丢弃修改并关闭？</p>
      </ConfirmDialog>
    </section>
  );
});
