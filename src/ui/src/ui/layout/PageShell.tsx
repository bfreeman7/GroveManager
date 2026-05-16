import React from "react";

type Props = {
  children: React.ReactNode;
};

export function PageShell({ children }: Props) {
  return <div className="page">{children}</div>;
}
