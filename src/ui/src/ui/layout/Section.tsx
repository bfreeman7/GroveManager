import React from "react";

type Props = {
  title: string;
  description?: string;
  id?: string;
  children: React.ReactNode;
  className?: string;
  headerAction?: React.ReactNode;
};

export function Section({ title, description, id, children, className, headerAction }: Props) {
  return (
    <section id={id} className={`section card ${className ?? ""}`.trim()}>
      <div className="sectionHeader">
        <div>
          <h2 className="sectionTitle">{title}</h2>
          {description ? <p className="sectionDesc">{description}</p> : null}
        </div>
        {headerAction ? <div className="sectionHeaderAction">{headerAction}</div> : null}
      </div>
      <div className="sectionBody">{children}</div>
    </section>
  );
}
