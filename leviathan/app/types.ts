export interface Ship {
  id: string;
  lat: number;
  lng: number;
  status: 'nominal' | 'delayed' | 'critical';
  cargo: string;
  destination: string;
}

export interface LogEntry {
  id: string;
  timestamp: string;
  message: string;
  severity: 'info' | 'warning' | 'critical';
}

export interface Facility {
  id: string;
  company: string;
  name: string;
  lat: number;
  lng: number;
  type: string;
  status: 'Nominal' | 'Warning' | 'Critical';
  powerDrawMW: number;
  hardwareHealth: {
    avgTemp: number;
    anomalies: string[];
  };
  compute: {
    gpusInUse: string;
    utilization: number;
    networkStatus: string;
  };
  inventory?: {
    material: string;
    level: string;
  }[];
}

export interface IntelPacket {
  src: string;
  vec: string;
  intel: string;
  sev: string;
  summary: string;
  analysis: string;
  date: string;
  author: string;
  link: string;
  riskLevel: 'CRITICAL' | 'MODERATE' | 'LOW' | 'NONE';
}

export interface GlobalSummary {
  timestamp: string;
  agent32_geopolitics: string;
  agent40_supply_chain: string;
  overallRiskLevel: 'CRITICAL' | 'MODERATE' | 'LOW' | 'NONE';
  sources: { src: string; link: string; intel: string; date: string }[];
}
