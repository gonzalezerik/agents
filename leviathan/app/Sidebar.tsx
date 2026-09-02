"use client";
import React, { useEffect, useState } from "react";
import { Globe, ShieldAlert, ChevronRight, ChevronDown, Building2, Server, AlertTriangle } from "lucide-react";
import { FACILITIES } from "./constants";
import { Facility, IntelPacket } from "./types";

export const Sidebar = ({ activeFacility, setActiveFacility, onSelectIntel }: any) => {
  const [mesh, setMesh] = useState<IntelPacket[]>([]);
  const [expandedCos, setExpandedCos] = useState<Record<string, boolean>>({ "NVIDIA": true, "IBM": true });

  useEffect(() => {
    const fetchMesh = async () => {
      try {
        const res = await fetch('/api/state', { cache: 'no-store' });
        if (!res.ok) return; 
        const data = await res.json();
        if (data && data.mesh_intel) setMesh(data.mesh_intel);
      } catch (e) { }
    };
    const itv = setInterval(fetchMesh, 1500);
    return () => clearInterval(itv);
  }, []);

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
        <h1 className="text-xl font-black tracking-tighter text-white uppercase flex items-center gap-2 italic">
          <Globe className="text-cyan-500 animate-spin-slow" size={20} />
          LEVIATHAN <span className="text-cyan-500 not-italic font-light">GOD-MESH</span>
        </h1>
      </div>

      <div className="p-4 bg-slate-950 border-b border-slate-800 h-[40vh] flex flex-col shrink-0">
        <div className="flex justify-between items-center mb-3">
          <span className="text-[10px] font-bold text-red-500 tracking-[0.4em] uppercase flex items-center gap-2">
            <ShieldAlert size={12} /> Edge AI Intel Feed
          </span>
          <span className="text-[9px] font-mono text-slate-500">VERIFIED // {mesh.length} VECTORS</span>
        </div>
        
        <div className="overflow-y-auto pr-2 custom-scrollbar flex-1 space-y-2">
          {mesh.length === 0 && <div className="text-xs font-mono text-slate-600 animate-pulse">Awaiting Dual-Model Verification...</div>}
          {mesh.map((packet, i) => {
            const riskUI = getRiskUI(packet.riskLevel);
            return (
              <div key={i} onClick={() => onSelectIntel(packet)} className={`text-[10px] font-mono border rounded p-3 cursor-pointer hover:border-cyan-500/80 transition-all group ${riskUI.class}`}>
                <div className="flex justify-between mb-2 items-center">
                  <div className="flex items-center gap-2">
                    {riskUI.icon}
                    <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-widest bg-slate-800 text-cyan-400`}>{packet.src}</span>
                  </div>
                  <span className="text-[8px] text-slate-500 flex items-center gap-1 group-hover:text-cyan-400 transition-colors">{packet.vec} <ChevronRight size={10} /></span>
                </div>
                <p className={`text-slate-200 leading-tight line-clamp-2 ${packet.riskLevel === 'CRITICAL' ? 'font-bold' : 'font-semibold'}`}>{packet.intel}</p>
              </div>
            );
          })}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 custom-scrollbar bg-black">
        {/* FACILITY GRID REMAINS THE SAME AS BEFORE */}
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
