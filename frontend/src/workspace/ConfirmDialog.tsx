import * as Dialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";

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

// Radix Dialog gives focus trap, Escape, and focus return for free — used by every
// workspace confirmation (save, discard, restore, close guard) so none reimplement it.
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
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="confirm-dialog" aria-describedby={undefined}>
          <Dialog.Title className="confirm-title">{title}</Dialog.Title>
          <div className="confirm-body">{children}</div>
          <div className="files-confirm-actions">
            <button type="button" className="files-action primary" disabled={confirmDisabled} onClick={onConfirm}>
              {confirmLabel}
            </button>
            <Dialog.Close asChild>
              <button type="button" className="files-action" disabled={confirmDisabled}>
                {cancelLabel}
              </button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
