import React from "react";
import {
  getOpenSprinklerLog,
  getOpenSprinklerSnapshot,
  postOpenSprinklerLogging,
  postOpenSprinklerStation,
} from "../../api";
import type { OpenSprinklerLogResponse, OpenSprinklerSnapshotConfigured } from "../../types";

export const LOG_HIST_DAYS = 7;
export const DEFAULT_RUN_SECONDS = 300;
const POLL_MS = 12000;

export function useOpenSprinkler() {
  const [snapshot, setSnapshot] = React.useState<OpenSprinklerSnapshotConfigured | null>(null);
  const [notConfigured, setNotConfigured] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [runLog, setRunLog] = React.useState<OpenSprinklerLogResponse | null>(null);
  const [logError, setLogError] = React.useState<string | null>(null);

  const [modalOpen, setModalOpen] = React.useState<{ id: number; name: string } | null>(null);
  const [modalSeconds, setModalSeconds] = React.useState(String(DEFAULT_RUN_SECONDS));
  const [modalLoading, setModalLoading] = React.useState(false);
  const [busySid, setBusySid] = React.useState<number | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [loggingBusy, setLoggingBusy] = React.useState(false);
  const [showRaw, setShowRaw] = React.useState(false);

  const reload = React.useCallback(async () => {
    try {
      setError(null);
      setLogError(null);
      const s = await getOpenSprinklerSnapshot();
      if (!s.configured) {
        setNotConfigured(true);
        setSnapshot(null);
        setRunLog(null);
      } else {
        setNotConfigured(false);
        setSnapshot(s);
        try {
          const log = await getOpenSprinklerLog(LOG_HIST_DAYS);
          setRunLog(log);
        } catch (e) {
          setRunLog(null);
          setLogError(e instanceof Error ? e.message : String(e));
        }
      }
    } catch (e) {
      setSnapshot(null);
      setRunLog(null);
      setNotConfigured(false);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void reload();
    const id = window.setInterval(() => void reload(), POLL_MS);
    return () => window.clearInterval(id);
  }, [reload]);

  const closeModal = React.useCallback(() => {
    setModalOpen(null);
    setActionError(null);
  }, []);

  React.useEffect(() => {
    if (!modalOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !modalLoading) closeModal();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [modalOpen, modalLoading, closeModal]);

  async function stopStation(sid: number) {
    setActionError(null);
    setBusySid(sid);
    try {
      await postOpenSprinklerStation({ sid, en: 0 });
      await reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusySid(null);
    }
  }

  async function confirmRun() {
    if (!modalOpen) return;
    const sec = Number.parseInt(String(modalSeconds).trim(), 10);
    if (!Number.isFinite(sec) || sec < 1 || sec > 64800) {
      setActionError("Duration must be between 1 and 64800 seconds.");
      return;
    }
    setModalLoading(true);
    setActionError(null);
    try {
      await postOpenSprinklerStation({ sid: modalOpen.id, en: 1, t: sec });
      closeModal();
      await reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setModalLoading(false);
    }
  }

  function openRunModal(s: { id: number; name: string }) {
    setActionError(null);
    setModalSeconds(String(DEFAULT_RUN_SECONDS));
    setModalOpen({ id: s.id, name: s.name });
  }

  async function toggleLogging(enabled: boolean) {
    if (loggingBusy) return;
    setLoggingBusy(true);
    setActionError(null);
    try {
      await postOpenSprinklerLogging({ lg: enabled ? 1 : 0 });
      await reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoggingBusy(false);
    }
  }

  const stationBusy = busySid !== null || modalLoading || loggingBusy;

  return {
    snapshot,
    notConfigured,
    error,
    loading,
    runLog,
    logError,
    reload,
    modalOpen,
    modalSeconds,
    setModalSeconds,
    modalLoading,
    busySid,
    actionError,
    loggingBusy,
    showRaw,
    setShowRaw,
    closeModal,
    stopStation,
    confirmRun,
    openRunModal,
    toggleLogging,
    stationBusy,
  };
}
