"use client";

import { useState, useRef, useEffect } from "react";

export default function AccessibilityWidget() {
  const [open, setOpen] = useState(false);
  const [description, setDescription] = useState("");
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const el = dialogRef.current;
    if (!el) return;
    const focusable = el.querySelectorAll<HTMLElement>(
      'button, input, textarea, [tabindex]:not([tabindex="-1"])'
    );
    focusable[0]?.focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        close();
        return;
      }
      if (e.key !== "Tab") return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first) { e.preventDefault(); last?.focus(); }
      } else {
        if (document.activeElement === last) { e.preventDefault(); first?.focus(); }
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!description.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/a11y-report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: window.location.href,
          description: description.trim(),
          userAgent: navigator.userAgent,
          email: email.trim() || undefined,
        }),
      });
      if (!res.ok) throw new Error("Submission failed");
      setSubmitted(true);
    } catch {
      setError("Failed to submit. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  function close() {
    setOpen(false);
    setDescription("");
    setEmail("");
    setSubmitted(false);
    setError(null);
    triggerRef.current?.focus();
  }

  const currentPath =
    typeof window !== "undefined" ? window.location.pathname : "";

  return (
    <>
      <button
        ref={triggerRef}
        onClick={() => setOpen(true)}
        aria-label="Report an accessibility issue"
        aria-haspopup="dialog"
        className="fixed bottom-4 right-4 z-40 flex items-center justify-center w-12 h-12 rounded-full bg-blue-600 text-white shadow-lg hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="currentColor"
          className="w-6 h-6"
          aria-hidden="true"
          focusable="false"
        >
          <path d="M12 2a2 2 0 1 1 0 4 2 2 0 0 1 0-4Zm-1 5.5h2c1.1 0 2 .9 2 2V14l1.5 3H16l-1-2.5h-6L8 17H6.5L8 14V9.5c0-1.1.9-2 2-2Z" />
        </svg>
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-50 bg-black/40"
            aria-hidden="true"
            onClick={close}
          />

          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="a11y-dialog-title"
            className="fixed bottom-20 right-4 z-50 w-80 rounded-xl shadow-2xl border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 p-5"
          >
            {submitted ? (
              <div>
                <h2 id="a11y-dialog-title" className="text-base font-semibold mb-2">
                  Thank you
                </h2>
                <p className="text-sm text-neutral-600 dark:text-neutral-400 mb-4">
                  Your report has been received. The issue will be reviewed
                  and addressed if it is a genuine accessibility barrier.
                  {email.trim() && " You will receive email updates as it progresses."}
                </p>
                <button
                  onClick={close}
                  className="w-full py-2 text-sm rounded-lg bg-neutral-100 dark:bg-neutral-800 hover:bg-neutral-200 dark:hover:bg-neutral-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500"
                >
                  Close
                </button>
              </div>
            ) : (
              <form onSubmit={handleSubmit}>
                <h2 id="a11y-dialog-title" className="text-base font-semibold mb-1">
                  Report an accessibility issue
                </h2>
                <p className="text-xs text-neutral-500 dark:text-neutral-400 mb-3">
                  Page: <span className="font-mono">{currentPath || "/"}</span>
                </p>

                <label htmlFor="a11y-description" className="block text-sm font-medium mb-1">
                  What happened?
                </label>
                <textarea
                  id="a11y-description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={4}
                  placeholder="e.g. I couldn't navigate the gallery with my keyboard, or the text was too hard to read in dark mode…"
                  className="w-full text-sm border border-neutral-300 dark:border-neutral-600 rounded-lg px-3 py-2 bg-transparent resize-none focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                  required
                  aria-describedby={error ? "a11y-error" : undefined}
                  aria-invalid={error ? "true" : undefined}
                />

                <label htmlFor="a11y-email" className="block text-sm font-medium mt-3 mb-1">
                  Email <span className="font-normal text-neutral-400">(optional — for status updates)</span>
                </label>
                <input
                  id="a11y-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="w-full text-sm border border-neutral-300 dark:border-neutral-600 rounded-lg px-3 py-2 bg-transparent focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                />

                {error && (
                  <p id="a11y-error" role="alert" className="text-xs text-red-600 dark:text-red-400 mt-1">
                    {error}
                  </p>
                )}

                <div className="flex gap-2 mt-3">
                  <button
                    type="submit"
                    disabled={loading || !description.trim()}
                    className="flex-1 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500"
                  >
                    {loading ? "Submitting…" : "Submit report"}
                  </button>
                  <button
                    type="button"
                    onClick={close}
                    className="py-2 px-3 text-sm rounded-lg bg-neutral-100 dark:bg-neutral-800 hover:bg-neutral-200 dark:hover:bg-neutral-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </div>
        </>
      )}
    </>
  );
}
