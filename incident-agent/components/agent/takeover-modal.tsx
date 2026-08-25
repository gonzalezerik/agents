"use client";

interface Incident {
  id: string;
  title: string;
  entity: string;
  summary: string;
  opened: string;
}

export function TakeoverModal({ incidents }: { incidents: Incident[] }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl bg-[#0F1011] rounded-xl border border-[#23252A] shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="bg-[#F0553F] px-6 py-4 border-b border-[#D94331]">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-full bg-white/10 flex items-center justify-center text-white">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6">
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
            </div>
            <div>
              <h2 className="text-xl font-semibold text-white">Incidents Needing Attention</h2>
              <p className="text-white/80 text-sm">Unacknowledged critical incidents from overnight</p>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6">
          {incidents.map((incident) => (
            <div key={incident.id} className="bg-[#161718] rounded-lg p-4 border-l-4 border-[#F0553F]">
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-medium text-[#D0D6E0]">{incident.title}</h3>
                <span className="text-xs text-[#F0553F] font-mono">#{incident.id}</span>
              </div>
              <div className="text-sm text-[#8A8F98] mb-2">
                Affected: <span className="font-mono text-[#D0D6E0]">{incident.entity}</span> ·
                Opened: <span className="font-mono text-[#62666D]">{incident.opened}</span>
              </div>
              <div className="bg-[#1D1F21] rounded p-3 text-xs text-[#8A8F98]">
                <span className="font-semibold text-[#62666D]">Agent Summary:</span> {incident.summary}
              </div>
            </div>
          ))}

          <div className="bg-[#1D1F21] rounded-lg p-4 text-sm text-[#8A8F98]">
            <p className="mb-2"><strong>What happened:</strong> The agent investigated but could not resolve these incidents automatically.</p>
            <p>
              <strong>Next steps:</strong> Review the details below, take appropriate action, and acknowledge to clear this notification.
            </p>
          </div>
        </div>

        {/* Actions */}
        <div className="border-t border-[#23252A] p-4 flex items-center justify-between">
          <button
            onClick={() => {}}
            className="px-4 py-2 rounded bg-[#7C87FF] text-[#08090A] text-sm font-medium hover:bg-[#6B76E0]"
          >
            Acknowledge All
          </button>
          <button
            onClick={() => {}}
            className="px-4 py-2 rounded border border-[#23252A] text-sm text-[#D0D6E0] hover:bg-[#161718]"
          >
            View All Incidents
          </button>
        </div>

        {/* Footer */}
        <div className="px-6 py-3 bg-[#08090A] text-xs text-[#62666D] text-center">
          This modal appears only for critical incidents the agent couldn't resolve. Warnings/info go to the feed.
        </div>
      </div>
    </div>
  );
}
