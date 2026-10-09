import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

const FRESHRSS_URL = process.env.FRESHRSS_URL || 'http://freshrss.freshrss.svc.cluster.local';
const FRESHRSS_USER = process.env.FRESHRSS_USER || 'admin';
const FRESHRSS_PASS = process.env.FRESHRSS_PASS || 'rabbit-forest-media-72';

async function getAuthToken(): Promise<string> {
  const res = await fetch(`${FRESHRSS_URL}/api/greader.php/accounts/ClientLogin`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: `Email=${FRESHRSS_USER}&Passwd=${encodeURIComponent(FRESHRSS_PASS)}`,
    cache: 'no-store',
  });
  const text = await res.text();
  const match = text.match(/Auth=(.+)/);
  return match ? match[1].trim() : '';
}

export async function GET() {
  try {
    const token = await getAuthToken();
    if (!token) return NextResponse.json({ items: [] }, { status: 502 });

    const res = await fetch(
      `${FRESHRSS_URL}/api/greader.php/reader/api/0/stream/contents/user/-/label/AI?output=json&n=30`,
      { headers: { Authorization: `GoogleLogin auth=${token}` }, cache: 'no-store' }
    );
    const data = await res.json();

    const items = (data.items || []).map((item: any) => ({
      id: item.id,
      title: item.title || '(no title)',
      source: item.origin?.title || 'Unknown',
      url: item.alternate?.[0]?.href || '#',
      published: item.published,
      summary: (item.summary?.content || item.content?.content || '')
        .replace(/<[^>]+>/g, '')
        .replace(/\s+/g, ' ')
        .trim()
        .slice(0, 280),
    }));

    return NextResponse.json({ items });
  } catch {
    return NextResponse.json({ items: [] }, { status: 500 });
  }
}
