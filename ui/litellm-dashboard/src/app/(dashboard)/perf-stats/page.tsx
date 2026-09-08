"use client";

// Embeds the local metrics dashboard (scripts/dashboard.py, served on the host
// machine at localhost:8093 -- see repo root for the script) as an iframe inside
// the Admin UI, instead of it living as a separate standalone page. The iframe
// renders client-side in the browser, so localhost:8093 resolves against the
// user's own machine regardless of where the LiteLLM proxy container runs.
const METRICS_DASHBOARD_URL = "http://localhost:8093";

export default function Metrics() {
  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      <iframe
        src={METRICS_DASHBOARD_URL}
        title="LiteLLM Metrics Dashboard"
        className="w-full flex-1 border-0"
      />
    </div>
  );
}
