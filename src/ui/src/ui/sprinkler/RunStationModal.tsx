import React from "react";

type Props = {
  station: { id: number; name: string };
  seconds: string;
  loading: boolean;
  error: string | null;
  onSecondsChange: (v: string) => void;
  onConfirm: () => void;
  onClose: () => void;
};

export function RunStationModal({
  station,
  seconds,
  loading,
  error,
  onSecondsChange,
  onConfirm,
  onClose,
}: Props) {
  return (
    <div
      className="modalBackdrop"
      role="presentation"
      onClick={() => {
        if (!loading) onClose();
      }}
    >
      <div
        className="modalCard"
        role="dialog"
        aria-modal="true"
        aria-labelledby="os-run-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div id="os-run-modal-title" className="modalTitle">
          Run station
        </div>
        <div className="modalSub">{station.name}</div>
        <div className="modalField">
          <label className="modalFieldLabel" htmlFor="os-run-seconds">
            Duration (seconds)
          </label>
          <input
            id="os-run-seconds"
            type="number"
            min={1}
            max={64800}
            value={seconds}
            disabled={loading}
            onChange={(e) => onSecondsChange(e.target.value)}
          />
        </div>
        {error ? <div className="inlineErr" style={{ marginBottom: 10 }}>{error}</div> : null}
        <div className="modalActions">
          <button type="button" className="btn secondary" disabled={loading} onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn" disabled={loading} onClick={onConfirm}>
            {loading ? "Running…" : "Run"}
          </button>
        </div>
      </div>
    </div>
  );
}
