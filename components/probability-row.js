import { formatPct } from "@/lib/fast-tracker";

export default function ProbabilityRow({ label, values, strong = false }) {
  const cells = [
    ["H", values?.home],
    ["D", values?.draw],
    ["A", values?.away],
  ];

  return (
    <div className={`prob-row ${strong ? "prob-row-strong" : ""}`}>
      <div className="prob-label">{label}</div>
      <div className="prob-values">
        {cells.map(([key, value]) => (
          <div className="prob-cell" key={key}>
            <span>{key}</span>
            <b>{formatPct(value)}</b>
            <i style={{ width: `${Math.max(0, Math.min(100, (value || 0) * 100))}%` }} />
          </div>
        ))}
      </div>
    </div>
  );
}
