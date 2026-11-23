import { useState } from "react";
import { limits, t, type Lang } from "./copy";

const SEEN = "raincheck-limits-seen";

export function LimitsPanel({ lang }: { lang: Lang }) {
  const [open, setOpen] = useState(() => {
    try {
      return sessionStorage.getItem(SEEN) !== "1";
    } catch {
      return true;
    }
  });

  function close() {
    setOpen(false);
    try {
      sessionStorage.setItem(SEEN, "1");
    } catch {
      /* The panel still closes for this visit. */
    }
  }

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="rounded-full border border-ink px-4 py-2 text-sm">
        {t(lang, "how")}
      </button>
    );
  }

  return (
    <aside className="rounded-2xl border border-stone-300 bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <h2 className="font-serif text-xl text-ink">{t(lang, "how")}</h2>
        <button type="button" onClick={close} className="rounded-full border border-ink px-3 py-1 text-sm">
          {t(lang, "hideHow")}
        </button>
      </div>
      <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-6 text-ink">
        {limits(lang).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </aside>
  );
}
