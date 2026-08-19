import { useState } from "react";
import { Collapsible as RadixCollapsible } from "radix-ui";
import { ChevronDown } from "lucide-react";

/** The one shared expand/reveal primitive behind "Ver qué falta" and "Ver
 * ubicación" -- proper aria-expanded/aria-controls wiring via Radix,
 * instead of two bespoke bits of local state (FA-017.1 §7). */
export function Collapsible({
  triggerLabel,
  children,
}: {
  triggerLabel: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <RadixCollapsible.Root open={open} onOpenChange={setOpen}>
      <RadixCollapsible.Trigger className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:text-primary-hover">
        {triggerLabel}
        <ChevronDown size={14} className={open ? "rotate-180 transition-transform" : "transition-transform"} />
      </RadixCollapsible.Trigger>
      <RadixCollapsible.Content className="mt-2">{children}</RadixCollapsible.Content>
    </RadixCollapsible.Root>
  );
}
