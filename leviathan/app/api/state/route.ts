import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function GET() {
  try {
    const meshPath = path.join(process.cwd(), 'public', 'mesh.json');
    const logsPath = path.join(process.cwd(), 'public', 'logs.json');

    let mesh_intel = [];
    let logs = [];
    let global_summary = null;

    // Safely read Mesh and the new Global Summary
    if (fs.existsSync(meshPath)) {
        try { 
            const parsedMesh = JSON.parse(fs.readFileSync(meshPath, 'utf8'));
            mesh_intel = parsedMesh.mesh_intel || []; 
            global_summary = parsedMesh.global_summary || null;
        } catch(e) {}
    }

    if (fs.existsSync(logsPath)) {
        try { logs = JSON.parse(fs.readFileSync(logsPath, 'utf8')).logs || []; } catch(e) {}
    }

    return NextResponse.json({ mesh_intel, logs, global_summary });
  } catch (error) {
    return NextResponse.json({ logs: [], mesh_intel: [] }, { status: 500 });
  }
}
