import { AlertDialog as RadixAlertDialog } from "radix-ui";

/** Real focus-trapped, Escape-to-close confirmation -- replaces
 * HistoryScreen's old bespoke inline two-button toggle (FA-017.1 §7/§24). */
export function AlertDialog({
  trigger,
  title,
  description,
  cancelLabel,
  confirmLabel,
  confirmVariant = "danger",
  onConfirm,
}: {
  trigger: React.ReactNode;
  title: string;
  description: string;
  cancelLabel: string;
  confirmLabel: string;
  confirmVariant?: "danger" | "primary";
  onConfirm: () => void;
}) {
  return (
    <RadixAlertDialog.Root>
      <RadixAlertDialog.Trigger asChild>{trigger}</RadixAlertDialog.Trigger>
      <RadixAlertDialog.Portal>
        <RadixAlertDialog.Overlay className="fixed inset-0 bg-neutral-900/40" />
        <RadixAlertDialog.Content className="fixed top-1/2 left-1/2 w-[90vw] max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-surface-elevated p-6 shadow-lg">
          <RadixAlertDialog.Title className="text-base font-semibold text-foreground">
            {title}
          </RadixAlertDialog.Title>
          <RadixAlertDialog.Description className="mt-2 text-sm text-foreground-muted">
            {description}
          </RadixAlertDialog.Description>
          <div className="mt-4 flex justify-end gap-2">
            <RadixAlertDialog.Cancel asChild>
              <button
                type="button"
                className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:bg-surface-muted"
              >
                {cancelLabel}
              </button>
            </RadixAlertDialog.Cancel>
            <RadixAlertDialog.Action asChild>
              <button
                type="button"
                onClick={onConfirm}
                className={
                  confirmVariant === "danger"
                    ? "rounded-md bg-danger px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
                    : "rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary-hover"
                }
              >
                {confirmLabel}
              </button>
            </RadixAlertDialog.Action>
          </div>
        </RadixAlertDialog.Content>
      </RadixAlertDialog.Portal>
    </RadixAlertDialog.Root>
  );
}
