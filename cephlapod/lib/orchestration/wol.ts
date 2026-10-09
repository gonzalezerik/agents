import dgram from "dgram";

/**
 * Send a Wake-on-LAN magic packet.
 * LXC 115 is on vmbr0 (same L2 as gpuhost), so a UDP broadcast reaches it
 * directly without any SSH hop. No root required for UDP.
 */
export async function sendWol(mac: string, broadcast = "localhost"): Promise<void> {
  const normalised = mac.replace(/[:\-]/g, "").toUpperCase();
  if (normalised.length !== 12) throw new Error(`Invalid MAC: ${mac}`);

  const macBytes = Buffer.from(normalised, "hex");
  // Magic packet: 6×0xFF + 16× MAC address
  const packet = Buffer.alloc(102);
  packet.fill(0xff, 0, 6);
  for (let i = 0; i < 16; i++) macBytes.copy(packet, 6 + i * 6);

  return new Promise((resolve, reject) => {
    const sock = dgram.createSocket("udp4");
    sock.once("error", reject);
    sock.bind(() => {
      sock.setBroadcast(true);
      sock.send(packet, 0, packet.length, 9, broadcast, (err) => {
        sock.close();
        if (err) reject(err);
        else resolve();
      });
    });
  });
}

/**
 * Poll a URL until it returns 200 or timeout elapses.
 * Used after WoL to detect when gpuhost's mc-agent is up.
 */
export async function waitForHttp(
  url: string,
  opts: { timeoutMs?: number; intervalMs?: number } = {}
): Promise<boolean> {
  const { timeoutMs = 180_000, intervalMs = 5_000 } = opts;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(3_000) });
      if (res.ok) return true;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return false;
}
