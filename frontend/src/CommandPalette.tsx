import * as Dialog from "@radix-ui/react-dialog";
import { Command, Search, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

export interface PaletteCommand {
  id: string;
  label: string;
  detail: string;
  keywords?: string[];
  run: (opener: HTMLButtonElement | null) => void;
}

export function CommandPalette({ commands, onOpenChange }: { commands: PaletteCommand[]; onOpenChange: (open: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const changeOpen = useCallback((next: boolean) => {
    if (next) {
      setQuery("");
      setActiveIndex(0);
    }
    setOpen(next);
    onOpenChange(next);
  }, [onOpenChange]);

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== "k") return;
      event.preventDefault();
      if (open) changeOpen(false);
      else if (!document.querySelector('[role="dialog"], dialog:modal')) changeOpen(true);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [changeOpen, open]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return commands;
    return commands.filter((command) =>
      [command.label, command.detail, ...(command.keywords ?? [])]
        .join(" ")
        .toLocaleLowerCase()
        .includes(needle),
    );
  }, [commands, query]);
  const selectedIndex = Math.min(activeIndex, Math.max(0, filtered.length - 1));

  const runCommand = (command: PaletteCommand) => {
    const opener = triggerRef.current;
    changeOpen(false);
    requestAnimationFrame(() => command.run(opener));
  };

  const handleSearchKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.nativeEvent.isComposing || filtered.length === 0) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const direction = event.key === "ArrowDown" ? 1 : -1;
      setActiveIndex((selectedIndex + direction + filtered.length) % filtered.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      runCommand(filtered[selectedIndex]);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={changeOpen}>
      <Dialog.Trigger asChild>
        <button ref={triggerRef} type="button" className="command-palette-trigger" aria-label="打开命令面板" title="命令面板（Ctrl/⌘ K）">
          <Command aria-hidden="true" />
          <kbd>Ctrl/⌘ K</kbd>
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className="command-palette"
          aria-describedby={undefined}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            searchRef.current?.focus();
          }}
        >
          <div className="command-palette-head">
            <div>
              <Dialog.Title>命令面板</Dialog.Title>
              <span>只执行当前 Workbench 已有动作</span>
            </div>
            <Dialog.Close asChild>
              <button type="button" className="icon-button" aria-label="关闭命令面板"><X aria-hidden="true" /></button>
            </Dialog.Close>
          </div>
          <label className="command-palette-search">
            <Search aria-hidden="true" />
            <input
              ref={searchRef}
              role="combobox"
              aria-label="搜索命令"
              aria-controls="command-palette-results"
              aria-expanded="true"
              aria-autocomplete="list"
              aria-activedescendant={filtered.length ? `command-option-${filtered[selectedIndex].id}` : undefined}
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setActiveIndex(0);
              }}
              onKeyDown={handleSearchKeyDown}
              placeholder="搜索命令或视图"
            />
            <kbd>Esc</kbd>
          </label>
          <div id="command-palette-results" className="command-palette-results" role="listbox" aria-label="命令结果">
            {filtered.length ? filtered.map((command, index) => (
              <button
                type="button"
                id={`command-option-${command.id}`}
                key={command.id}
                role="option"
                aria-selected={index === selectedIndex}
                className="command-palette-option"
                data-active={index === selectedIndex}
                tabIndex={-1}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => runCommand(command)}
              >
                <span>{command.label}</span>
                <small>{command.detail}</small>
              </button>
            )) : <p className="command-palette-empty" role="status">没有匹配的命令</p>}
          </div>
          <p className="command-palette-hint">↑↓ 选择 · Enter 执行 · Esc 关闭</p>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
