"use client";
import React, { useEffect, useState, useRef } from "react";
import { Ship, LogEntry, Facility, IntelPacket, GlobalSummary } from "./types";
import { INITIAL_SHIPS } from "./constants";
import { Sidebar } from "./Sidebar";
import { GlobeView } from "./GlobeView";
import { X, Terminal, Cpu, Brain, Activity, Link as LinkIcon, Clock, User, Server, AlertTriangle, Zap, Package, Globe } from "lucide-react";

export default function LeviathanDashboard() {
  const [ships, setShips] = useState<Ship[]>(INITIAL_SHIPS);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [globalSync, setGlobalSync] = useState<GlobalSummary | null>(null);
  
  const [activeFacility, setActiveFacility] = useState<Facility | null>(null);
  const [selectedIntel, setSelectedIntel] = useState<IntelPacket | null>(null);
  
  const [showDebug, setShowDebug] = useState(false);
  const [showGlobalState, setShowGlobalState] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch('/api/state', { cache: 'no-store' });
        if (!res.ok) return; 
        const data = await res.json();
        if (data && data.logs && data.logs.length > 0) setLogs(data.logs);
        if (data && data.global_summary) setGlobalSync(data.global_summary);
      } catch (e) { }
    };

    const interval = setInterval(fetchData, 1500);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (scrollRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
      if (scrollHeight - scrollTop - clientHeight < 200) {
        scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "auto" });
      }
    }
  }, [logs]);

  const handleFacilityClick = (fac: Facility) => { setSelectedIntel(null); setShowGlobalState(false); setActiveFacility(fac); };
  const handleIntelClick = (intel: IntelPacket) => { setActiveFacility(null); setShowGlobalState(false); setSelectedIntel(intel); };
  const handleGlobalClick = () => { setActiveFacility(null); setSelectedIntel(null); setShowGlobalState(!showGlobalState); };

  const renderTriangle = (risk: string) => {
    if (risk === "CRITICAL") return <AlertTriangle size={16} className="text-red-500 animate-pulse inline mr-1" />;
    if (risk === "MODERATE") return <AlertTriangle size={16} className="text-orange-500 inline mr-1" />;
    if (risk === "LOW") return <AlertTriangle size={16} className="text-yellow-500 inline mr-1" />;
    return null;
  }

  return (
    <div className="flex h-screen w-screen bg-black overflow-hidden text-white relative">
      <Sidebar activeFacility={activeFacility} setActiveFacility={handleFacilityClick} onSelectIntel={handleIntelClick} />
      <GlobeView ships={ships} activeFacility={activeFacility} />

      {/* FACILITY POPUP */}
      {activeFacility && (
        <div className="absolute top-24 left-[460px] w-[500px] bg-slate-950/80 backdrop-blur-2xl border border-slate-700 rounded-2xl p-6 shadow-[0_0_50px_rgba(0,0,0,0.8)] z-50">
          <button onClick={() => setActiveFacility(null)} className="absolute top-4 right-4 text-slate-500 hover:text-white transition-colors"><X size={20} /></button>
          <div className="mb-6 border-b border-slate-800 pb-4">
            <span className={`inline-block px-2 py-1 rounded text-[9px] font-bold uppercase tracking-widest mb-2 ${activeFacility.status === 'Critical' ? 'bg-red-500/20 text-red-400 border border-red-500/50' : 'bg-cyan-900/40 text-cyan-400 border border-cyan-800'}`}>{activeFacility.type}</span>
            <h2 className="text-xl font-black text-white tracking-tight uppercase">{activeFacility.name}</h2>
          </div>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div className="bg-black/50 border border-slate-800 rounded-lg p-4">
              <h3 className="text-[10px] text-slate-500 uppercase font-bold mb-3 flex items-center gap-2"><Server size={12}/> Compute Core</h3>
              <div className="text-sm font-mono text-cyan-400 mb-1">{activeFacility.compute?.gpusInUse || "N/A GPUs"}</div>
              <div className="text-[10px] text-slate-400">Load: {activeFacility.compute?.utilization || 0}%</div>
            </div>
            <div className="bg-black/50 border border-slate-800 rounded-lg p-4">
              <h3 className="text-[10px] text-slate-500 uppercase font-bold mb-3 flex items-center gap-2"><Zap size={12}/> Power & Thermal</h3>
              <div className="text-sm font-mono text-amber-400 mb-1">{Math.floor(activeFacility.powerDrawMW)} MW Draw</div>
              <div className={`text-[10px] ${activeFacility.hardwareHealth.avgTemp > 80 ? 'text-red-400' : 'text-slate-400'}`}>Avg Temp: {activeFacility.hardwareHealth.avgTemp}°C</div>
            </div>
          </div>
        </div>
      )}

      {/* INTEL POPUP */}
      {selectedIntel && (
        <div className="absolute top-24 left-[460px] w-[550px] bg-slate-950/80 backdrop-blur-2xl border border-slate-700 rounded-2xl p-6 shadow-[0_0_50px_rgba(0,0,0,0.8)] z-50 animate-in slide-in-from-left-4 duration-200">
          <button onClick={() => setSelectedIntel(null)} className="absolute top-4 right-4 text-slate-500 hover:text-white transition-colors"><X size={20} /></button>
          <div className="mb-4">
            <div className="flex flex-wrap gap-2 mb-3">
              <span className={`px-2 py-1 rounded text-[9px] font-bold uppercase tracking-widest ${selectedIntel.sev === 'critical' ? 'bg-red-500/20 text-red-400 border border-red-500/50' : 'bg-slate-800 text-cyan-400 border border-cyan-900'}`}>{selectedIntel.src}</span>
            </div>
            <h2 className="text-lg font-semibold text-slate-100 leading-snug mb-3">{selectedIntel.intel}</h2>
            <div className="flex flex-wrap gap-x-4 gap-y-2 text-[10px] font-mono text-slate-400 bg-black/40 p-2 rounded border border-slate-800">
              <div className="flex items-center gap-1"><Clock size={10} className="text-cyan-500"/> {selectedIntel.date}</div>
              <div className="flex items-center gap-1"><User size={10} className="text-cyan-500"/> {selectedIntel.author}</div>
              {selectedIntel.link && <a href={selectedIntel.link} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-cyan-400 hover:text-cyan-300"><LinkIcon size={10}/> Source Protocol</a>}
            </div>
          </div>
          <div className="space-y-4 border-t border-slate-800 pt-4">
            <div className="bg-cyan-950/20 border border-cyan-900/50 rounded-lg p-4">
              <h3 className="text-[10px] font-bold text-cyan-500 uppercase tracking-widest mb-2 flex items-center gap-2"><Cpu size={12} /> Granite 3.2 Synthesis</h3>
              <p className="text-sm text-cyan-100/90 leading-relaxed font-serif">{selectedIntel.summary}</p>
            </div>
            <div className="bg-purple-950/20 border border-purple-900/50 rounded-lg p-4 relative overflow-hidden">
              <div className="absolute top-0 right-0 w-16 h-16 bg-purple-500/10 rounded-full blur-xl"></div>
              <h3 className="text-[10px] font-bold text-purple-400 uppercase tracking-widest mb-2 flex items-center gap-2 relative z-10"><Brain size={12} /> Granite 4.0 Assessment</h3>
              <p className="text-sm text-purple-100/90 leading-relaxed font-serif relative z-10">{selectedIntel.analysis}</p>
              <div className="mt-4 pt-3 border-t border-purple-900/50 font-bold tracking-widest text-[10px]">
                {renderTriangle(selectedIntel.riskLevel)} {selectedIntel.riskLevel !== "NONE" ? `IMPACT RISK: ${selectedIntel.riskLevel}` : "NO SUPPLY CHAIN IMPACT"}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* --- GLOBAL STATE COLLABORATIVE POPUP --- */}
      {showGlobalState && (
        <div className="absolute top-24 right-32 w-[600px] bg-slate-950/90 backdrop-blur-2xl border border-cyan-500/30 rounded-2xl p-6 shadow-[0_0_50px_rgba(6,182,212,0.15)] z-50 animate-in slide-in-from-right-4 duration-200">
           <button onClick={() => setShowGlobalState(false)} className="absolute top-4 right-4 text-slate-500 hover:text-white transition-colors"><X size={20} /></button>
           
           <div className="flex justify-between items-start mb-6 border-b border-slate-800 pb-4">
              <div>
                <h2 className="text-xl font-black text-white tracking-tight uppercase flex items-center gap-2"><Globe className="text-cyan-500 animate-pulse"/> Global Risk Sync</h2>
                <div className="text-[10px] font-mono text-slate-500 mt-2">
                  {globalSync ? `LAST SYNC: ${globalSync.timestamp}` : "STATUS: INITIATING MULTI-AGENT HANDSHAKE..."}
                </div>
              </div>
              
              {globalSync && (
                <div className="flex flex-col items-end">
                  <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest mb-1">DEFCON CONSENSUS</span>
                  <div className={`flex items-center gap-2 px-3 py-1.5 rounded border font-bold tracking-widest text-xs ${globalSync.overallRiskLevel === 'CRITICAL' ? 'bg-red-950/40 border-red-500/50 text-red-400 shadow-[0_0_15px_rgba(239,68,68,0.2)]' : globalSync.overallRiskLevel === 'MODERATE' ? 'bg-orange-950/40 border-orange-500/50 text-orange-400' : globalSync.overallRiskLevel === 'LOW' ? 'bg-yellow-950/40 border-yellow-500/50 text-yellow-400' : 'bg-slate-900 border-slate-700 text-slate-400'}`}>
                    {renderTriangle(globalSync.overallRiskLevel)} {globalSync.overallRiskLevel}
                  </div>
                </div>
              )}
           </div>

           {!globalSync ? (
             <div className="flex flex-col items-center justify-center py-10 space-y-4">
                <Activity size={32} className="text-cyan-500 animate-pulse" />
                <p className="text-xs font-mono text-slate-400 text-center">Awaiting Granite 3.2 and Granite 4.0 synchronization.<br/>Global state report generates every 3 minutes based on active threat vectors...</p>
             </div>
           ) : (
             <div className="space-y-4">
                <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
                   <div className="flex items-center gap-2 mb-2">
                      <div className="h-6 w-6 rounded bg-cyan-900/50 flex items-center justify-center border border-cyan-500/50"><Cpu size={12} className="text-cyan-400"/></div>
                      <span className="text-[10px] font-bold text-cyan-500 uppercase tracking-widest">Granite 3.2 (Geopolitics)</span>
                   </div>
                   <p className="text-sm text-slate-300 leading-relaxed font-serif pl-8 border-l-2 border-slate-800">{globalSync.agent32_geopolitics}</p>
                </div>
                <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
                   <div className="flex items-center gap-2 mb-2">
                      <div className="h-6 w-6 rounded bg-purple-900/50 flex items-center justify-center border border-purple-500/50"><Brain size={12} className="text-purple-400"/></div>
                      <span className="text-[10px] font-bold text-purple-400 uppercase tracking-widest">Granite 4.0 (Architecture)</span>
                   </div>
                   <p className="text-sm text-slate-300 leading-relaxed font-serif pl-8 border-l-2 border-slate-800">{globalSync.agent40_supply_chain}</p>
                </div>
                <div className="mt-4 pt-4 border-t border-slate-800">
                   <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-3 block">Threat Sources Evaluated</span>
                   <ul className="space-y-3 max-h-40 overflow-y-auto custom-scrollbar pr-2">
                      {globalSync.sources.map((src, i) => (
                         <li key={i} className="text-[10px] font-mono text-slate-400 flex flex-col gap-1 pb-2 border-b border-slate-800/50 last:border-0">
                            <div className="flex items-start gap-2">
                               <AlertTriangle size={10} className="text-red-500 mt-0.5 shrink-0"/>
                               <a href={src.link} target="_blank" rel="noreferrer" className="hover:text-cyan-400 truncate flex-1">[{src.src}] {src.intel}</a>
                            </div>
                            <div className="pl-4 text-[8px] text-slate-500 flex items-center gap-1">
                               <Clock size={8} /> Evaluated: {globalSync.timestamp} | Published: {src.date}
                            </div>
                         </li>
                      ))}
                   </ul>
                </div>
             </div>
           )}
        </div>
      )}

      {/* Buttons on the Right */}
      <div className="absolute bottom-10 right-10 z-[60] flex flex-col gap-4">
        <button onClick={handleGlobalClick} className={`bg-slate-900 border p-4 rounded-full transition-all shadow-[0_0_20px_rgba(6,182,212,0.15)] group ${showGlobalState ? 'border-cyan-500 bg-cyan-900/20' : 'border-slate-700 hover:border-cyan-500/50 hover:bg-slate-800'}`}>
          <Activity size={28} className={showGlobalState ? "text-cyan-400" : "text-slate-500 group-hover:text-cyan-400"} />
        </button>
        <button onClick={() => setShowDebug(!showDebug)} className="bg-slate-900 border border-slate-700 p-4 rounded-full hover:border-purple-500/50 hover:bg-slate-800 transition-all shadow-[0_0_20px_rgba(168,85,247,0.15)] group">
          <Terminal size={28} className="text-purple-500 group-hover:text-purple-400" />
        </button>
      </div>

      {/* Terminal Popup (Unchanged) */}
      {showDebug && (
        <div className="absolute inset-0 z-[100] flex items-center justify-center bg-black/95 p-8">
          <div className="w-full h-full max-h-[85vh] max-w-[90vw] bg-slate-950 border border-purple-500/30 rounded-lg shadow-2xl flex flex-col overflow-hidden animate-in zoom-in duration-150">
            <div className="p-4 border-b border-slate-800 flex justify-between items-center bg-slate-900/50">
              <span className="text-slate-400 font-mono text-xs flex items-center gap-2"><Terminal size={14}/> Leviathan Core Systems Log</span>
              <button onClick={() => setShowDebug(false)} className="text-slate-500 hover:text-white"><X size={24} /></button>
            </div>
            <div ref={scrollRef} className="flex-1 overflow-y-auto overflow-x-hidden p-6 font-mono text-sm bg-black/40 custom-scrollbar">
              <div className="space-y-4">
                {logs.map((log) => (
                    <div key={log.id} className={`flex gap-4 pb-3 border-b border-slate-900/40 ${log.severity === 'critical' ? 'text-red-400 font-bold bg-red-950/20 -mx-2 px-2 py-1' : log.severity === 'warning' ? 'text-amber-400' : 'text-slate-300'}`}>
                      <span className="text-slate-600 shrink-0 w-24">[{log.timestamp}]</span>
                      <span className="flex-1 whitespace-pre-wrap">{log.message}</span>
                    </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
