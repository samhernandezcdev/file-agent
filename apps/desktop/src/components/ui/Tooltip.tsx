import { Tooltip as RadixTooltip } from "radix-ui";

/** Reserved for a merely-truncated filename (FA-017.1 §16) -- a full
 * absolute path uses its own explicit "Ver ubicación" Collapsible
 * disclosure instead, never a tooltip-only affordance. */
export function Tooltip({ content, children }: { content: string; children: React.ReactNode }) {
  return (
    <RadixTooltip.Provider delayDuration={300}>
      <RadixTooltip.Root>
        <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
        <RadixTooltip.Portal>
          <RadixTooltip.Content
            className="max-w-xs rounded-md bg-neutral-900 px-2 py-1 text-xs text-white shadow-md"
            sideOffset={4}
          >
            {content}
            <RadixTooltip.Arrow className="fill-neutral-900" />
          </RadixTooltip.Content>
        </RadixTooltip.Portal>
      </RadixTooltip.Root>
    </RadixTooltip.Provider>
  );
}
