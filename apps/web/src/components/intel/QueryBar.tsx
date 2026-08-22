import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

const SUGGESTIONS = ["Areas with >7% yield", "Compare Dubai South with JVC", "Top sales activity", "Yield under 4%"];

export function QueryBar({ onQuery, explanation }: { onQuery: (q: string) => void; explanation: string | null }) {
  const [value, setValue] = useState("");

  const submit = (q: string) => {
    if (!q.trim()) return;
    onQuery(q);
  };

  return (
    <div className="absolute bottom-5 left-1/2 -translate-x-1/2 w-full max-w-xl px-4 z-10">
      <AnimatePresence>
        {explanation && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            className="mb-2 rounded-lg border border-[var(--accent)]/25 bg-[var(--surface)]/95 backdrop-blur px-4 py-2.5 text-xs text-[var(--text)] shadow-lg"
          >
            <span className="text-[var(--accent)] font-medium mr-1.5">Dubai Intelligence:</span>
            {explanation}
          </motion.div>
        )}
      </AnimatePresence>

      <div className="rounded-full border border-[var(--border)] bg-[var(--surface)]/95 backdrop-blur-md shadow-xl px-2 py-2 flex items-center gap-2">
        <span className="pl-2.5 text-[var(--accent)] text-sm">&#10022;</span>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              submit(value);
              setValue("");
            }
          }}
          placeholder="Ask Dubai Intelligence..."
          className="flex-1 bg-transparent text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none py-1.5"
        />
        <button
          onClick={() => {
            submit(value);
            setValue("");
          }}
          className="text-xs font-medium rounded-full px-4 py-1.5 bg-[var(--accent)] text-[var(--bg)] hover:opacity-90 transition-opacity"
        >
          Ask
        </button>
      </div>
      <div className="flex flex-wrap gap-1.5 mt-2 justify-center">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => submit(s)}
            className="text-[10px] text-[var(--text-muted)] border border-[var(--border)]/70 rounded-full px-2.5 py-1 hover:text-[var(--text)] hover:border-[var(--accent)]/50 transition-colors"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
