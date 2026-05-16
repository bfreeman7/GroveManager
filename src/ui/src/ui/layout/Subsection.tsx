import React from "react";

type Label = "Status" | "Control" | "History";

type Props = {
  label: Label;
  children: React.ReactNode;
  className?: string;
  hint?: string;
};

export function Subsection({ label, children, className, hint }: Props) {
  return (
    <div className={`subsection ${className ?? ""}`.trim()}>
      <div className="subsectionHead">
        <span className="subsectionChip">{label}</span>
        {hint ? <span className="subsectionHint">{hint}</span> : null}
      </div>
      <div className="subsectionContent">{children}</div>
    </div>
  );
}
