import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { refreshData, uploadFile } from "../lib/api";
import { Card, SectionHeader } from "../components/ui";

export function ImportData() {
  const [dragOver, setDragOver] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  const uploadMutation = useMutation({
    mutationFn: uploadFile,
    onSuccess: (result) => {
      setLog((l) => [`Imported: ${JSON.stringify(result)}`, ...l]);
      queryClient.invalidateQueries();
    },
    onError: (err: Error) => setLog((l) => [`Error: ${err.message}`, ...l]),
  });

  const refreshMutation = useMutation({
    mutationFn: refreshData,
    onSuccess: (result) => {
      setLog((l) => [`Refreshed: ${JSON.stringify(result)}`, ...l]);
      queryClient.invalidateQueries();
    },
    onError: (err: Error) => setLog((l) => [`Error: ${err.message}`, ...l]),
  });

  const handleFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    Array.from(files).forEach((f) => uploadMutation.mutate(f));
  };

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold">Import Data</h1>
      <p className="text-xs text-[var(--text-muted)]">
        Drop a DLD sales or rental CSV export below, or click "Refresh Data" to re-scan the DATA FILES DLD folder for new/changed files. Rebuilding
        the warehouse over the full historical dataset currently takes 1-3 minutes — this is synchronous, so the button will show "Working..." until done.
      </p>

      <Card
        className={`p-10 text-center border-dashed ${dragOver ? "border-[var(--accent)]" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files); }}
      >
        <p className="text-sm text-[var(--text-muted)] mb-3">Drag & drop CSV files here, or</p>
        <button
          onClick={() => inputRef.current?.click()}
          className="text-sm bg-[var(--accent)] text-[var(--bg)] rounded px-4 py-2 font-medium"
        >
          Choose Files
        </button>
        <input ref={inputRef} type="file" accept=".csv" multiple className="hidden" onChange={(e) => handleFiles(e.target.files)} />
      </Card>

      <div>
        <button
          onClick={() => refreshMutation.mutate()}
          disabled={refreshMutation.isPending}
          className="text-sm border border-[var(--border)] rounded px-4 py-2 hover:bg-[var(--hover-overlay)] disabled:opacity-50"
        >
          {refreshMutation.isPending ? "Working..." : "Refresh Data (scan DATA FILES DLD)"}
        </button>
      </div>

      {(uploadMutation.isPending) && <p className="text-xs text-[var(--accent)]">Importing and rebuilding warehouse — this can take a few minutes...</p>}

      <Card className="p-4">
        <SectionHeader title="Activity Log" />
        <div className="space-y-1 text-xs font-mono max-h-64 overflow-y-auto">
          {log.length === 0 && <div className="text-[var(--text-muted)]">No activity yet.</div>}
          {log.map((line, i) => (
            <div key={i} className="text-[var(--text-muted)] break-all">{line}</div>
          ))}
        </div>
      </Card>
    </div>
  );
}
