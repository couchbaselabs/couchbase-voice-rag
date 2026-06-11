"use client";

import { useState, useRef, useEffect } from "react";
import * as api from "@/lib/api";
import { isApiError, toastApiError } from "@/lib/errors";
import type { UploadedFile } from "@/types";

interface FileUploadProps {
  files: UploadedFile[];
  onRefresh: () => void;
}

type Progress = { processed: number; total: number };

export default function FileUpload({ files, onRefresh }: FileUploadProps) {
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [vectorizing, setVectorizing] = useState<Map<string, Progress>>(new Map());
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Poll vectorizing files for completion and surface Capella workflow
  // processedFiles / totalFiles so the row can render a determinate
  // progress bar instead of an indeterminate shimmer.
  useEffect(() => {
    if (vectorizing.size === 0) {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    pollRef.current = setInterval(() => {
      void (async () => {
        let anyDone = false;
        for (const filename of vectorizing.keys()) {
          try {
            const status = await api.getUploadStatus(filename);
            if (status.status === "completed" || status.status === "failed") {
              anyDone = true;
              setVectorizing((prev) => {
                const next = new Map(prev);
                next.delete(filename);
                return next;
              });
            } else if (status.status === "vectorizing") {
              const processed = status.processed_files ?? 0;
              const total = status.total_files ?? 0;
              setVectorizing((prev) => {
                const cur = prev.get(filename);
                if (cur && cur.processed === processed && cur.total === total) {
                  return prev;
                }
                const next = new Map(prev);
                next.set(filename, { processed, total });
                return next;
              });
            }
          } catch {
            /* ignore */
          }
        }
        if (anyDone) onRefresh();
      })();
    }, 1000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [vectorizing, onRefresh]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setError("");
    setUploading(true);

    try {
      const result = await api.uploadDocument(file);
      if (result.status === "vectorizing") {
        setVectorizing((prev) => new Map(prev).set(result.filename, { processed: 0, total: 0 }));
      }
      onRefresh();
    } catch (err) {
      if (isApiError(err) && (err.status === 413 || err.status === 400)) {
        // Keep size / extension / MIME-mismatch errors inline next to the
        // input so the user sees them while still looking at the file picker.
        setError(err.detail);
      } else {
        toastApiError(err, "Upload failed.");
      }
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDelete = async (filename: string) => {
    setDeleting(filename);
    try {
      await api.deleteDocument(filename);
      onRefresh();
    } catch (err) {
      toastApiError(err, `Failed to delete ${filename}.`);
    } finally {
      setDeleting(null);
    }
  };

  const getStatusLabel = (f: UploadedFile) => {
    const prog = vectorizing.get(f.filename);
    if (prog) {
      return prog.total > 0 ? `Vectorizing... (${prog.processed}/${prog.total})` : "Vectorizing...";
    }
    if (f.embedding_method === "capella" && f.workflow_name) {
      return `AI Workflow: ${f.workflow_name}`;
    }
    if (f.embedding_method === "local") {
      return "Local embedding";
    }
    if (f.embedding_method === "pending") {
      return "Vectorizing...";
    }
    return "";
  };

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold tracking-wider text-gray-400 uppercase">
        Knowledge Base
      </h3>

      {files.map((f) => {
        const statusLabel = getStatusLabel(f);
        const prog = vectorizing.get(f.filename);
        const isVectorizing = prog !== undefined || f.embedding_method === "pending";
        const determinate = !!prog && prog.total > 0;
        const pct = determinate ? Math.min(100, (prog.processed / prog.total) * 100) : 100;
        return (
          <div
            key={f.filename}
            className="flex items-center justify-between rounded bg-gray-800 px-2 py-1.5 text-sm"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-gray-300">{f.filename}</p>
              <p className="text-xs text-gray-400">
                {f.chunk_count} chunks
                {statusLabel && (
                  <>
                    {" · "}
                    {isVectorizing ? (
                      <span className="animate-pulse text-yellow-400">{statusLabel}</span>
                    ) : (
                      statusLabel
                    )}
                  </>
                )}
              </p>
              {isVectorizing && (
                <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-gray-700">
                  <div
                    className={
                      determinate
                        ? "h-1.5 rounded-full bg-red-500 transition-all duration-500"
                        : "h-1.5 animate-[shimmer_2s_linear_infinite] rounded-full bg-gradient-to-r from-red-500 via-orange-400 to-red-500 bg-[length:200%_100%]"
                    }
                    style={{ width: `${pct}%` }}
                    role="progressbar"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    {...(determinate ? { "aria-valuenow": Math.round(pct) } : {})}
                  />
                </div>
              )}
            </div>
            <button
              onClick={() => {
                void handleDelete(f.filename);
              }}
              disabled={deleting === f.filename}
              className="ml-2 text-gray-400 hover:text-red-400 disabled:opacity-50"
              title="Delete"
              aria-label={`Delete ${f.filename}`}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                aria-hidden="true"
                className="h-4 w-4"
              >
                <path
                  fillRule="evenodd"
                  d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.519.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z"
                  clipRule="evenodd"
                />
              </svg>
            </button>
          </div>
        );
      })}

      {error && <p className="text-xs text-red-400">{error}</p>}

      {uploading ? (
        <div
          className="w-full rounded-lg border-2 border-gray-600 bg-gray-800 px-3 py-2.5"
          role="status"
          aria-live="polite"
        >
          <div className="flex items-center gap-2">
            <svg
              className="h-4 w-4 shrink-0 animate-spin text-red-500"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              />
            </svg>
            <span className="text-sm text-gray-300">Uploading & chunking...</span>
          </div>
        </div>
      ) : (
        <label className="block w-full cursor-pointer rounded-lg border-2 border-dashed border-gray-600 px-3 py-2 text-center transition-colors hover:border-red-500 hover:bg-gray-800">
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.txt"
            onChange={(e) => {
              void handleUpload(e);
            }}
            className="hidden"
          />
          <span className="text-sm text-gray-400">Upload PDF / DOCX / TXT</span>
        </label>
      )}
    </div>
  );
}
