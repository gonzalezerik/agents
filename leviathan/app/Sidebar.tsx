"use client";
import React, { useEffect, useState } from "react";
import { Globe, ShieldAlert, ChevronRight, ChevronDown, Building2, Server, AlertTriangle, Rss, ExternalLink } from "lucide-react";
import { FACILITIES } from "./constants";
import { Facility, IntelPacket } from "./types";

interface RssItem {
  id: string;
  title: string;
  source: string;
  url: string;
  published: number;
  summary: string;
}

function timeAgo(ts: number): string {
  const diff = Math.floor(Date.now() / 1000) - ts;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export const Sidebar = ({ activeFacility, setActiveFacility, onSelectIntel }: any) => {
  const [mesh, setMesh] = useState<IntelPacket[]>([]);
  const [expandedCos, setExpandedCos] = useState<Record<string, boolean>>({ "NVIDIA": true, "IBM": true });
  const [feedMode, setFeedMode] = useState<'intel' | 'rss'>('intel');
  const [rssItems, setRssItems] = useState<RssItem[]>([]);
  const [rssLoading, setRssLoading] = useState(false);

  useEffect(() => {
    const fetchMesh = async () => {
      try {
        const res = await fetch('/api/state', { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        if (data?.mesh_intel) setMesh(data.mesh_intel);
      } catch {}
    };
    const itv = setInterval(fetchMesh, 1500);
    return () => clearInterval(itv);
  }, []);

  useEffect(() => {
    if (feedMode !== 'rss' || rssItems.length > 0) return;
    setRssLoading(true);
    fetch('/api/rss', { cache: 'no-store' })
      .then(r => r.json())
      .then(d => setRssItems(d.items || []))
      .catch(() => {})
      .finally(() => setRssLoading(false));
  }, [feedMode]);

  const toggleCompany = (co: string) => setExpandedCos(prev => ({ ...prev, [co]: !prev[co] }));

  const groupedFacilities = FACILITIES.reduce((acc, fac) => {
    if (!acc[fac.company]) acc[fac.company] = {};
    if (!acc[fac.company][fac.type]) acc[fac.company][fac.type] = [];
    acc[fac.company][fac.type].push(fac);
    return acc;
  }, {} as Record<string, Record<string, Facility[]>>);

  const getRiskUI = (risk: string) => {
    if (risk === "CRITICAL") return { icon: <AlertTriangle size={14} className="text-red-500 animate-pulse" />, class: "border-red-500/80 bg-red-950/20 shadow-[0_0_15px_rgba(239,68,68,0.15)]" };
    if (risk === "MODERATE") return { icon: <AlertTriangle size={14} className="text-orange-500" />, class: "border-orange-500/40 bg-slate-900/40" };
    if (risk === "LOW") return { icon: <AlertTriangle size={14} className="text-yellow-500" />, class: "border-yellow-500/30 bg-slate-900/20" };
    return { icon: null, class: "border-slate-900/50 bg-slate-900/20" };
  };

  return (
    <aside className="w-[440px] h-screen flex flex-col border-r border-slate-800 bg-black text-slate-400 z-40 relative">
      <div className="p-6 border-b border-slate-800 bg-slate-900/40 shrink-0">
        <h1 className="text-xl font-black tracking-tighter text-white uppercase flex items-center gap-2">
          <Globe className="text-cyan-500 animate-spin-slow" size={20} />
          Leviathan
        </h1>
      </div>

      <div className="bg-slate-950 border-b border-slate-800 h-[40vh] flex flex-col shrink-0">
        {/* Feed toggle tabs */}
        <div className="flex border-b border-slate-800 shrink-0">
          <button
            onClick={() => setFeedMode('intel')}
            className={`flex-1 flex items-center justify-center gap-2 py-2.5 text-[10px] font-bold uppercase tracking-widest transition-colors
              ${feedMode === 'intel' ? 'text-cyan-400 border-b-2 border-cyan-500 bg-slate-900/60' : 'text-slate-600 hover:text-slate-400'}`}
          >
            <ShieldAlert size={11} /> AI Intel Feed
          </button>
          <button
            onClick={() => setFeedMode('rss')}
            className={`flex-1 flex items-center justify-center gap-2 py-2.5 text-[10px] font-bold uppercase tracking-widest transition-colors
              ${feedMode === 'rss' ? 'text-cyan-400 border-b-2 border-cyan-500 bg-slate-900/60' : 'text-slate-600 hover:text-slate-400'}`}
          >
            <Rss size={11} /> Live AI News
          </button>
        </div>

        <div className="overflow-y-auto pr-2 custom-scrollbar flex-1 space-y-2 p-3">
          {feedMode === 'intel' && (
            <>
              <div className="flex justify-between items-center mb-2">
                <span className="text-[9px] font-mono text-slate-500">{mesh.length} items · AI-analyzed</span>
              </div>
              {mesh.length === 0 && (
                <div className="text-xs font-mono text-slate-600 animate-pulse">Awaiting analysis — press the scan button to start.</div>
              )}
              {mesh.map((packet, i) => {
                const riskUI = getRiskUI(packet.riskLevel);
                return (
                  <div key={i} onClick={() => onSelectIntel(packet)} className={`text-[10px] font-mono border rounded p-3 cursor-pointer hover:border-cyan-500/80 transition-all group ${riskUI.class}`}>
                    <div className="flex justify-between mb-2 items-center">
                      <div className="flex items-center gap-2">
                        {riskUI.icon}
                        <span className="px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-widest bg-slate-800 text-cyan-400">{packet.src}</span>
                      </div>
                      <span className="text-[8px] text-slate-500 flex items-center gap-1 group-hover:text-cyan-400 transition-colors">{packet.vec} <ChevronRight size={10} /></span>
                    </div>
                    <p className={`text-slate-200 leading-tight line-clamp-2 ${packet.riskLevel === 'CRITICAL' ? 'font-bold' : 'font-semibold'}`}>{packet.intel}</p>
                  </div>
                );
              })}
            </>
          )}

          {feedMode === 'rss' && (
            <>
              {rssLoading && <div className="text-xs font-mono text-slate-600 animate-pulse pt-2">Loading live feed...</div>}
              {!rssLoading && rssItems.length === 0 && (
                <div className="text-xs font-mono text-slate-600 pt-2">No items found.</div>
              )}
              {rssItems.map((item) => (
                <a
                  key={item.id}
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                  className="block text-[10px] font-mono border border-slate-900/50 bg-slate-900/20 rounded p-3 hover:border-cyan-500/50 hover:bg-slate-900/60 transition-all group"
                >
                  <div className="flex justify-between items-center mb-1.5">
                    <span className="px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-widest bg-slate-800 text-cyan-400">{item.source}</span>
                    <span className="flex items-center gap-1 text-[8px] text-slate-600 group-hover:text-slate-400">
                      {timeAgo(item.published)} <ExternalLink size={8} />
                    </span>
                  </div>
                  <p className="text-slate-200 font-semibold leading-tight line-clamp-2 mb-1">{item.title}</p>
                  {item.summary && (
                    <p className="text-slate-500 leading-tight line-clamp-2">{item.summary}</p>
                  )}
                </a>
              ))}
            </>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 custom-scrollbar bg-black">
        <span className="text-[9px] font-bold text-slate-600 uppercase tracking-widest pl-1 mb-3 block">Global Infrastructure Network</span>
        <div className="space-y-4">
          {Object.entries(groupedFacilities).map(([company, typesMap]) => (
            <div key={company} className="border border-slate-800 rounded-lg overflow-hidden bg-slate-950/30">
              <button onClick={() => toggleCompany(company)} className="w-full flex justify-between items-center p-3 bg-slate-900/80 hover:bg-slate-800 transition-colors border-b border-slate-800">
                <div className="flex items-center gap-2"><Building2 size={14} className="text-cyan-500" /><span className="text-xs font-bold text-white uppercase tracking-widest">{company}</span></div>
                {expandedCos[company] ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>
              {expandedCos[company] && (
                <div className="p-2 space-y-3">
                  {Object.entries(typesMap).map(([type, nodes]) => (
                    <div key={type} className="pl-2">
                      <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest flex items-center gap-1 mb-1"><Server size={10} /> {type}</span>
                      <div className="space-y-1 mt-2 border-l border-slate-800 pl-2">
                        {nodes.map((fac) => (
                          <div key={fac.id} onClick={() => setActiveFacility(fac)} className={`group p-2 rounded cursor-pointer transition-all flex justify-between items-center ${activeFacility?.id === fac.id ? 'bg-cyan-500/20 border border-cyan-500/50' : 'hover:bg-slate-800/50 border border-transparent'}`}>
                            <span className={`text-[10px] font-mono tracking-tight ${activeFacility?.id === fac.id ? 'text-cyan-300' : 'text-slate-300'}`}>{fac.name}</span>
                            <span className={`h-1.5 w-1.5 rounded-full ${fac.status === 'Critical' ? 'bg-red-500 animate-pulse' : fac.status === 'Warning' ? 'bg-amber-500' : 'bg-cyan-500'}`}></span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
};
