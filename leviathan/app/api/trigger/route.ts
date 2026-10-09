import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

export const dynamic = 'force-dynamic';

const RATE_LIMIT_MS = 5 * 60 * 1000;
const TRIGGER_FILE = path.join(process.cwd(), 'public', 'trigger.json');

export async function POST() {
  try {
    let lastTriggeredAt = 0;
    if (fs.existsSync(TRIGGER_FILE)) {
      try {
        const data = JSON.parse(fs.readFileSync(TRIGGER_FILE, 'utf8'));
        lastTriggeredAt = data.triggered_at || 0;
      } catch {}
    }

    const now = Date.now();
    const elapsed = now - lastTriggeredAt;

    if (elapsed < RATE_LIMIT_MS) {
      const remainingSec = Math.ceil((RATE_LIMIT_MS - elapsed) / 1000);
      return NextResponse.json({ error: 'rate_limited', remainingSec }, { status: 429 });
    }

    fs.writeFileSync(TRIGGER_FILE, JSON.stringify({ triggered_at: now, processed: false }));
    return NextResponse.json({ ok: true });
  } catch {
    return NextResponse.json({ error: 'internal' }, { status: 500 });
  }
}
