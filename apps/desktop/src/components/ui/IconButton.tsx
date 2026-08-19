import type { ButtonHTMLAttributes } from "react";

export function IconButton({
  label,
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={`inline-flex h-6 w-6 items-center justify-center rounded text-foreground-muted hover:bg-surface-muted hover:text-foreground cursor-pointer ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
