import { useEffect, useId, useRef, type ReactNode } from "react";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  onOpenChange: (open: boolean) => void;
  confirmLabel: string;
  cancelLabel: string;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  children: ReactNode;
}

// Native nested dialogs stay above the workspace's mobile top layer, contain
// focus and return it to the invoking control on close.
export function ConfirmDialog({
  open,
  title,
  onOpenChange,
  confirmLabel,
  cancelLabel,
  confirmDisabled,
  onConfirm,
  children,
}: ConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog || !open) return;
    dialog.showModal();
    return () => dialog.close();
  }, [open]);
  return (
    <dialog ref={ref} className="confirm-dialog" aria-labelledby={titleId}
      onCancel={(event) => { event.preventDefault(); event.stopPropagation(); if (!confirmDisabled) onOpenChange(false); }}
      onKeyDown={(event) => event.stopPropagation()}>
      <h2 id={titleId} className="confirm-title">{title}</h2>
      <div className="confirm-body">{children}</div>
      <div className="files-confirm-actions">
        <button type="button" className="files-action primary" disabled={confirmDisabled} onClick={onConfirm}>
          {confirmLabel}
        </button>
        <button type="button" className="files-action" disabled={confirmDisabled} onClick={() => onOpenChange(false)}>
          {cancelLabel}
        </button>
      </div>
    </dialog>
  );
}
