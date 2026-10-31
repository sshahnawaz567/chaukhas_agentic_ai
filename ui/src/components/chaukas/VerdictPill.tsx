import type { Verdict } from "@/lib/chaukas-types";
import { cn } from "@/lib/utils";

const toneClasses: Record<Verdict, string> = {
  ALLOW: "bg-allow text-primary-foreground",
  NEEDS_CONFIRMATION: "bg-confirm text-primary-foreground",
  BLOCK: "bg-block text-primary-foreground",
};

export function VerdictPill({
  tone,
  children,
  className,
}: {
  tone: Verdict;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide",
        toneClasses[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export const verdictBorderClasses: Record<Verdict, string> = {
  ALLOW: "border-allow bg-allow/5",
  NEEDS_CONFIRMATION: "border-confirm bg-confirm/5",
  BLOCK: "border-block bg-block/5",
};

export const verdictTextClasses: Record<Verdict, string> = {
  ALLOW: "text-allow",
  NEEDS_CONFIRMATION: "text-confirm",
  BLOCK: "text-block",
};
