"use client";

import { useState } from "react";
import { Sidebar } from "@/components/ui/sidebar";
import { TopBar } from "@/components/ui/topbar";
import { AgentTimeline } from "@/components/agent/agent-timeline";
import { TakeoverModal } from "@/components/agent/takeover-modal";

export default function AgentCenterPage() {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // Mock incidents for takeover modal
  const incidents = [
    { id: "a1", title: "Booking API Down", entity: "lash", summary: "3 failed health probes; DB connection refused; suspects opsdb pool", opened: "02:14 (6h 30m ago)" },
  ];

  return (
    <>
      <Sidebar isOpen={sidebarOpen} />
      <div className="flex flex-col flex-1 min-w-0 bg-[#08090A]">
        <TopBar sidebarOpen={sidebarOpen} onToggleSidebar={() => setSidebarOpen(!sidebarOpen)} />
        <main className="flex-1 overflow-y-auto p-6">
          {/* Header */}
          <div className="mb-6">
            <h1 className="text-2xl font-semibold text-[#D0D6E0] mb-2">Agent Center</h1>
            <div className="flex items-center gap-3 text-sm text-[#8A8F98]">
              <span className="px-3 py-1 rounded bg-[#62666D]/10 text-[#62666D] border border-[#23252A]">
                Mode: report-only
              </span>
              <span className="px-3 py-1 rounded bg-[#F0553F]/10 text-[#F0553F] border border-[#23252A]">
                Write tools: disabled
              </span>
              <span className="px-3 py-1 rounded bg-[#40C463]/10 text-[#40C463] border border-[#23252A]">
                Playbooks: 0 enabled
              </span>
            </div>
            <p className="mt-2 text-[#62666D]">Agent activity, incident investigations, and audit trail</p>
          </div>

          {/* Agent Timeline */}
          <AgentTimeline />

          {/* Takeover Modal (if critical unresolved incidents) */}
          <TakeoverModal incidents={incidents} />
        </main>
      </div>
    </>
  );
}
