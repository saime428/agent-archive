import { useEffect, useRef } from "react";
import * as monaco from "monaco-editor/editor/editor.api.js";
import EditorWorker from "monaco-editor/editor/editor.worker?worker";
import "monaco-editor/languages/definitions/css/register.js";
import "monaco-editor/languages/definitions/dockerfile/register.js";
import "monaco-editor/languages/definitions/html/register.js";
import "monaco-editor/languages/definitions/ini/register.js";
import "monaco-editor/languages/definitions/javascript/register.js";
import "monaco-editor/languages/definitions/markdown/register.js";
import "monaco-editor/languages/definitions/powershell/register.js";
import "monaco-editor/languages/definitions/python/register.js";
import "monaco-editor/languages/definitions/shell/register.js";
import "monaco-editor/languages/definitions/typescript/register.js";
import "monaco-editor/languages/definitions/xml/register.js";
import "monaco-editor/languages/definitions/yaml/register.js";

import type { ResolvedMode } from "../theme";

declare global {
  interface Window {
    MonacoEnvironment?: { getWorker: () => Worker };
  }
}

window.MonacoEnvironment = { getWorker: () => new EditorWorker() };

export interface MonacoEditorProps {
  path: string;
  value: string;
  openPaths: string[];
  readOnly: boolean;
  mode: ResolvedMode;
  jumpLine: number | null;
  jumpKey: number;
  onChange: (value: string) => void;
  onSave: () => void;
}

function languageForPath(path: string): string {
  const name = path.toLowerCase().split("/").at(-1) ?? path.toLowerCase();
  if (name === "dockerfile") return "dockerfile";
  const extension = name.includes(".") ? name.slice(name.lastIndexOf(".")) : "";
  return {
    ".css": "css",
    ".htm": "html",
    ".html": "html",
    ".ini": "ini",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "plaintext",
    ".md": "markdown",
    ".mdx": "markdown",
    ".ps1": "powershell",
    ".py": "python",
    ".sh": "shell",
    ".toml": "ini",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
  }[extension] ?? "plaintext";
}

function modelUri(path: string): monaco.Uri {
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  return monaco.Uri.parse(`inmemory://agent-workspace/${encoded}`);
}

export default function MonacoEditor({
  path,
  value,
  openPaths,
  readOnly,
  mode,
  jumpLine,
  jumpKey,
  onChange,
  onSave,
}: MonacoEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const modelsRef = useRef(new Map<string, monaco.editor.ITextModel>());
  const viewStatesRef = useRef(new Map<string, monaco.editor.ICodeEditorViewState | null>());
  const activePathRef = useRef(path);
  const onChangeRef = useRef(onChange);
  const onSaveRef = useRef(onSave);
  const syncingRef = useRef(false);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  useEffect(() => {
    onSaveRef.current = onSave;
  }, [onSave]);

  useEffect(() => {
    if (!containerRef.current) return;
    const models = modelsRef.current;
    const viewStates = viewStatesRef.current;
    const editor = monaco.editor.create(containerRef.current, {
      ariaLabel: "文件编辑器",
      automaticLayout: true,
      contextmenu: true,
      editContext: false,
      fontFamily: "Geist Mono Variable, Consolas, monospace",
      fontSize: 13,
      lineNumbersMinChars: 3,
      minimap: { enabled: false },
      model: null,
      padding: { top: 10, bottom: 10 },
      readOnly: true,
      readOnlyMessage: { value: "点击编辑后才能修改此文件。" },
      renderWhitespace: "selection",
      scrollBeyondLastLine: false,
      stickyScroll: { enabled: false },
      theme: "vs",
      wordWrap: "on",
    });
    editorRef.current = editor;
    const changeListener = editor.onDidChangeModelContent(() => {
      if (!syncingRef.current) onChangeRef.current(editor.getValue());
    });
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => onSaveRef.current());

    return () => {
      changeListener.dispose();
      editor.dispose();
      models.forEach((model) => model.dispose());
      models.clear();
      viewStates.clear();
      editorRef.current = null;
    };
  }, []); // Monaco owns its mutable editor instance; later props update it below.

  useEffect(() => {
    monaco.editor.setTheme(mode === "dark" ? "vs-dark" : "vs");
  }, [mode]);

  useEffect(() => {
    editorRef.current?.updateOptions({
      readOnly,
      domReadOnly: readOnly,
      readOnlyMessage: { value: readOnly ? "此文件当前只读。" : "" },
    });
  }, [readOnly]);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;
    let model = modelsRef.current.get(path);
    if (!model) {
      const uri = modelUri(path);
      model = monaco.editor.getModel(uri) ?? monaco.editor.createModel(value, languageForPath(path), uri);
      modelsRef.current.set(path, model);
    } else if (model.getValue() !== value) {
      syncingRef.current = true;
      model.setValue(value);
      syncingRef.current = false;
    }

    if (editor.getModel() !== model) {
      const previousPath = activePathRef.current;
      if (editor.getModel()) viewStatesRef.current.set(previousPath, editor.saveViewState());
      editor.setModel(model);
      activePathRef.current = path;
      const viewState = viewStatesRef.current.get(path);
      if (viewState) editor.restoreViewState(viewState);
      editor.layout();
    }
  }, [path, value]);

  useEffect(() => {
    const open = new Set(openPaths);
    modelsRef.current.forEach((model, modelPath) => {
      if (!open.has(modelPath)) {
        model.dispose();
        modelsRef.current.delete(modelPath);
        viewStatesRef.current.delete(modelPath);
      }
    });
  }, [openPaths]);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || jumpLine === null) return;
    const line = Math.min(Math.max(jumpLine, 1), editor.getModel()?.getLineCount() ?? 1);
    editor.setPosition({ lineNumber: line, column: 1 });
    editor.revealLineInCenter(line);
    editor.focus();
  }, [jumpKey, jumpLine]);

  return <div className="files-monaco" ref={containerRef} data-editor-path={path} />;
}
