import type { PlannedStep } from "@/lib/chaukas-types";

function formatParam(value: string | number | null): string {
  if (typeof value === "number") return value.toLocaleString("en-IN");
  if (value === null) return "null";
  return `"${value}"`;
}

/** retrigger_payout(settlement_id="SET-71209", amount=1,00,000) */
export function StepCall({ step }: { step: PlannedStep }) {
  const params = Object.entries(step.params);
  return (
    <code className="block break-words rounded-xl bg-ink px-4 py-3 font-mono text-base leading-relaxed text-primary-foreground">
      <span className="text-cyan">{step.action_type}</span>(
      {params.map(([key, value], index) => (
        <span key={key}>
          <span className="text-primary-foreground/70">{key}</span>=
          <span className="font-bold">{formatParam(value)}</span>
          {index < params.length - 1 ? ", " : ""}
        </span>
      ))}
      )
    </code>
  );
}
