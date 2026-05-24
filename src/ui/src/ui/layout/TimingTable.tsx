import React from "react";
import type { TimingCell } from "../shared/opensprinklerTiming";

export type TimingTableColumn = {
  key: string;
  header: string;
};

export type TimingTableRow = {
  key: string;
  label: string;
  cells: Record<string, TimingCell | string>;
};

type Props = {
  columns: TimingTableColumn[];
  rows: TimingTableRow[];
  emptyMessage?: string;
};

function renderCell(cell: TimingCell | string) {
  if (typeof cell === "string") {
    return <span className="timingCellPrimary">{cell}</span>;
  }
  return (
    <div className={`timingCell ${cell.emphasis ? "timingCell--active" : ""}`}>
      <div className="timingCellPrimary">{cell.primary}</div>
      {cell.time ? <div className="timingCellTime">{cell.time}</div> : null}
      {cell.relative ? <div className="timingCellRelative">{cell.relative}</div> : null}
      {cell.secondary ? <div className="timingCellSecondary">{cell.secondary}</div> : null}
    </div>
  );
}

export function TimingTable({ columns, rows, emptyMessage = "No data." }: Props) {
  if (!rows.length) {
    return <div className="muted">{emptyMessage}</div>;
  }

  return (
    <>
      <div className="timingTableWrap timingTableWrap--desktop">
        <table className="timingTable">
          <thead>
            <tr>
              <th scope="col" className="timingTableLabelCol">
                Station
              </th>
              {columns.map((c) => (
                <th scope="col" key={c.key}>
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <th scope="row" className="timingTableStation">
                  {row.label}
                </th>
                {columns.map((c) => (
                  <td key={c.key}>{renderCell(row.cells[c.key] ?? "—")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="timingMobileList">
        {rows.map((row) => (
          <article className="timingMobileCard" key={row.key}>
            <h4 className="timingMobileCardTitle">{row.label}</h4>
            {columns.map((c) => (
              <div className="timingMobileRow" key={c.key}>
                <div className="timingMobileRowLabel">{c.header}</div>
                <div className="timingMobileRowValue">{renderCell(row.cells[c.key] ?? "—")}</div>
              </div>
            ))}
          </article>
        ))}
      </div>
    </>
  );
}
