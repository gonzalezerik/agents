"use client";
import React, { useRef, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { Ship, Facility } from "./types";
import { RED_ZONE_POLYGON, SHIPPING_ARCS, FACILITIES } from "./constants";

const Globe = dynamic(() => import("react-globe.gl"), { ssr: false });

interface GlobeViewProps {
  ships: Ship[];
  activeFacility: Facility | null;
}

export const GlobeView: React.FC<GlobeViewProps> = ({ ships = [], activeFacility = null }) => {
  const globeEl = useRef<any>(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    if (activeFacility && globeEl.current && isReady) {
      globeEl.current.pointOfView(
        { lat: activeFacility.lat, lng: activeFacility.lng, altitude: 2.0 },
        1800
      );
    }
  }, [activeFacility, isReady]);

  return (
    <main className="flex-1 relative bg-black overflow-hidden h-full w-full">
      <Globe
        ref={globeEl}
        onGlobeReady={() => setIsReady(true)}
        globeImageUrl="//unpkg.com/three-globe/example/img/earth-night.jpg"
        backgroundImageUrl="//unpkg.com/three-globe/example/img/night-sky.png"
        atmosphereColor="#0ea5e9"
        atmosphereAltitude={0.15}

        labelsData={FACILITIES}
        labelLat="lat"
        labelLng="lng"
        labelText="name"
        labelSize={0.6}
        labelDotRadius={0.4}
        labelColor={(d: any) => 
          activeFacility?.id === d.id ? "#ffffff" : 
          d.status === 'Critical' ? '#ef4444' : '#22d3ee'
        }

        pointsData={ships}
        pointLat="lat"
        pointLng="lng"
        pointColor={() => "#f59e0b"}
        pointRadius={0.5}

        arcsData={SHIPPING_ARCS}
        arcStartLat={(d: any) => d.start.lat}
        arcStartLng={(d: any) => d.start.lng}
        arcEndLat={(d: any) => d.end.lat}
        arcEndLng={(d: any) => d.end.lng}
        arcColor={() => "rgba(0, 255, 255, 0.4)"}
        arcDashLength={0.4}
        arcDashAnimateTime={2000}

        autoRotate={!activeFacility}
        autoRotateSpeed={0.5}
      />
    </main>
  );
};
