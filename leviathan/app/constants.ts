import { Ship, Facility } from "./types";

export const INITIAL_SHIPS: Ship[] = [
  { id: "1", lat: 26.5074, lng: 56.1278, status: "critical", cargo: "EUV Components", destination: "Taiwan" },
  { id: "2", lat: 35.6762, lng: 139.6503, status: "nominal", cargo: "Wafer Shipment", destination: "USA" },
  { id: "3", lat: 40.7128, lng: -74.0060, status: "nominal", cargo: "Server Racks", destination: "Europe" },
];

// Generates highly realistic, company-specific telemetry for the Digital Twin Popups
const getTechData = (company: string, type: string, status: string) => {
  const isFoundry = type.includes("Foundry");
  
  let gpus = "N/A";
  if (company === "NVIDIA") gpus = "32,768x Blackwell B200";
  else if (company === "GOOGLE") gpus = "16,384x TPU v5p Pods";
  else if (company === "MICROSOFT" || company === "META") gpus = "24,576x Hopper H100";
  else if (company === "AMD") gpus = "12,288x Instinct MI300X";
  else if (company === "IBM") gpus = "8,192x Heron Quantum Processors";
  else if (isFoundry) gpus = "12x ASML High-NA EUV Scanners";

  return {
    powerDrawMW: isFoundry ? 420 + Math.random() * 150 : 120 + Math.random() * 80,
    hardwareHealth: {
      avgTemp: status === "Critical" ? 92 : status === "Warning" ? 78 : 34,
      anomalies: status === "Critical" ? ["Coolant pressure drop detected", "Thermal throttling active"] : status === "Warning" ? ["Power grid fluctuation"] : []
    },
    compute: {
      gpusInUse: gpus,
      utilization: status === "Critical" ? 42 : 94,
      networkStatus: status === "Critical" ? "Packet Loss Detected" : "Nominal"
    },
    inventory: isFoundry ? [
      { material: "Neon Gas (High-Purity)", level: status === "Critical" ? "12%" : "84%" },
      { material: "Silicon Wafers (300mm)", level: "92%" }
    ] : [
      { material: "Liquid Coolant", level: status === "Warning" ? "41%" : "96%" }
    ]
  };
};

export const FACILITIES: Facility[] = [
  // IBM
  { id: "IBM-1", company: "IBM", name: "Poughkeepsie Quantum", lat: 41.693, lng: -73.921, type: "Quantum R&D", status: "Nominal", ...getTechData("IBM", "Quantum R&D", "Nominal") },
  { id: "IBM-2", company: "IBM", name: "Cloud Frankfurt", lat: 50.110, lng: 8.682, type: "Datacenter", status: "Warning", ...getTechData("IBM", "Datacenter", "Warning") },
  { id: "IBM-3", company: "IBM", name: "Research Tokyo", lat: 35.676, lng: 139.650, type: "R&D", status: "Nominal", ...getTechData("IBM", "R&D", "Nominal") },
  
  // NVIDIA
  { id: "NV-1", company: "NVIDIA", name: "Eos Supercomputer (Santa Clara)", lat: 37.354, lng: -121.955, type: "AI Datacenter", status: "Nominal", ...getTechData("NVIDIA", "AI Datacenter", "Nominal") },
  { id: "NV-2", company: "NVIDIA", name: "Taipei Logistics Hub", lat: 25.032, lng: 121.565, type: "Logistics", status: "Critical", ...getTechData("NVIDIA", "Logistics", "Critical") },
  { id: "NV-3", company: "NVIDIA", name: "Tel Aviv R&D (Mellanox)", lat: 32.085, lng: 34.781, type: "R&D", status: "Warning", ...getTechData("NVIDIA", "R&D", "Warning") },

  // TSMC & ASML (The Backbone)
  { id: "TSMC-1", company: "TSMC", name: "Fab 18 (Tainan)", lat: 23.104, lng: 120.291, type: "Foundry", status: "Nominal", ...getTechData("TSMC", "Foundry", "Nominal") },
  { id: "TSMC-2", company: "TSMC", name: "Fab 21 (Arizona)", lat: 33.800, lng: -112.112, type: "Foundry", status: "Warning", ...getTechData("TSMC", "Foundry", "Warning") },
  { id: "ASML-1", company: "ASML", name: "Veldhoven HQ", lat: 51.405, lng: 5.404, type: "Equipment Supplier", status: "Nominal", ...getTechData("ASML", "Equipment Supplier", "Nominal") },

  // HYPERSCALERS (Google, Meta, Microsoft)
  { id: "GOOG-1", company: "GOOGLE", name: "Council Bluffs TPU Pod", lat: 41.261, lng: -95.860, type: "AI Datacenter", status: "Nominal", ...getTechData("GOOGLE", "AI Datacenter", "Nominal") },
  { id: "MSFT-1", company: "MICROSOFT", name: "Azure Dublin", lat: 53.349, lng: -6.260, type: "AI Datacenter", status: "Nominal", ...getTechData("MICROSOFT", "AI Datacenter", "Nominal") },
  { id: "META-1", company: "META", name: "Prineville Grand Compute", lat: 44.299, lng: -120.834, type: "AI Datacenter", status: "Nominal", ...getTechData("META", "AI Datacenter", "Nominal") },

  // AMD & INTEL
  { id: "INTC-1", company: "INTEL", name: "Ohio One Campus", lat: 40.058, lng: -82.812, type: "Foundry", status: "Nominal", ...getTechData("INTEL", "Foundry", "Nominal") },
  { id: "AMD-1", company: "AMD", name: "Austin Compute Core", lat: 30.267, lng: -97.743, type: "AI Datacenter", status: "Nominal", ...getTechData("AMD", "AI Datacenter", "Nominal") }
];

export const RED_ZONE_POLYGON = [
  { type: "Feature", properties: { id: "HORMUZ" }, geometry: { type: "Polygon", coordinates: [[[55.8, 26.1], [55.8, 27.2], [56.8, 27.2], [56.8, 26.1], [55.8, 26.1]]] } }
];
export const SHIPPING_ARCS = [];
