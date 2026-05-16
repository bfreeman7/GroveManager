import React from "react";

type Props = {
  title: string;
  children: React.ReactNode;
  variant?: "default" | "active" | "muted";
};

export function StatCard({ title, children, variant = "default" }: Props) {
  return (
    <div className={`statCard statCard--${variant}`}>
      <div className="statCardTitle">{title}</div>
      <div className="statCardBody">{children}</div>
    </div>
  );
}
