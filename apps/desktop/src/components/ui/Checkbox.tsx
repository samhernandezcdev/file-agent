import { Checkbox as RadixCheckbox } from "radix-ui";
import { Check, Minus } from "lucide-react";

export function Checkbox({
  checked,
  onCheckedChange,
  label,
  disabled,
}: {
  checked: boolean | "indeterminate";
  onCheckedChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <RadixCheckbox.Root
      checked={checked}
      onCheckedChange={(next) => onCheckedChange(next === true)}
      disabled={disabled}
      aria-label={label}
      className="flex h-4 w-4 shrink-0 items-center justify-center rounded border border-border-strong bg-surface data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=indeterminate]:border-primary data-[state=indeterminate]:bg-primary disabled:cursor-not-allowed disabled:opacity-60"
    >
      <RadixCheckbox.Indicator className="text-primary-foreground">
        {checked === "indeterminate" ? <Minus size={12} /> : <Check size={12} />}
      </RadixCheckbox.Indicator>
    </RadixCheckbox.Root>
  );
}
