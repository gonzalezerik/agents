/**
 * Dependency-free SMTP email sender using Node.js built-in net/tls.
 * Supports plain SMTP (port 25, internal relay) and direct TLS (port 465).
 * Set SMTP_SECURE=true for port-465 TLS. STARTTLS (port 587) is not supported
 * directly — use a local relay or port 465 instead.
 *
 * Required env vars: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM
 */
import * as net from "net";
import * as tls from "tls";

const host  = () => process.env.SMTP_HOST ?? "";
const port  = () => parseInt(process.env.SMTP_PORT ?? "465");
const user  = () => process.env.SMTP_USER ?? "";
const pass  = () => process.env.SMTP_PASS ?? "";
const from  = () => process.env.SMTP_FROM ?? "noreply@gonzalezerik.com";
const secure = () => process.env.SMTP_SECURE !== "false"; // default TLS

export async function sendEmail(
  to: string,
  subject: string,
  html: string
): Promise<boolean> {
  if (!host() || !to.includes("@")) return false;

  return new Promise((resolve) => {
    const socket: net.Socket = secure()
      ? (tls.connect({ host: host(), port: port(), rejectUnauthorized: false }) as unknown as net.Socket)
      : net.createConnection({ host: host(), port: port() });

    let buf = "";
    let step = 0;
    const settled = { done: false };
    const finish = (ok: boolean) => {
      if (settled.done) return;
      settled.done = true;
      socket.destroy();
      resolve(ok);
    };

    socket.setTimeout(15_000);
    socket.on("timeout", () => finish(false));
    socket.on("error", () => finish(false));

    const send = (line: string) => socket.write(line + "\r\n");

    const body = [
      `From: ${from()}`,
      `To: ${to}`,
      `Subject: ${subject}`,
      `MIME-Version: 1.0`,
      `Content-Type: text/html; charset=utf-8`,
      ``,
      html,
      `.`,
    ].join("\r\n");

    function handle(line: string) {
      const code = parseInt(line.slice(0, 3));
      const last = line[3] !== "-";
      if (!last) return; // wait for last line of multi-line response
      switch (step) {
        case 0: // greeting
          if (code !== 220) { finish(false); return; }
          send("EHLO mission-control"); step = 1; break;
        case 1: // EHLO
          if (code !== 250) { finish(false); return; }
          if (user()) { send("AUTH LOGIN"); step = 2; }
          else { send(`MAIL FROM:<${from()}>`); step = 4; }
          break;
        case 2: // AUTH LOGIN — username prompt
          if (code !== 334) { finish(false); return; }
          send(Buffer.from(user()).toString("base64")); step = 3; break;
        case 3: // AUTH LOGIN — password prompt
          if (code !== 334) { finish(false); return; }
          send(Buffer.from(pass()).toString("base64")); step = 4; break;
        case 4: // AUTH result or skip-auth
          if (user() && code !== 235) { finish(false); return; }
          if (!user() && code !== 250) { finish(false); return; }
          // after auth success, fall through to MAIL FROM
          if (step === 4 && user()) { send(`MAIL FROM:<${from()}>`); step = 5; break; }
          send(`MAIL FROM:<${from()}>`); step = 5; break;
        case 5: // MAIL FROM
          if (code !== 250) { finish(false); return; }
          send(`RCPT TO:<${to}>`); step = 6; break;
        case 6: // RCPT TO
          if (code !== 250) { finish(false); return; }
          send("DATA"); step = 7; break;
        case 7: // DATA prompt
          if (code !== 354) { finish(false); return; }
          socket.write(body + "\r\n"); step = 8; break;
        case 8: // message accepted
          if (code !== 250) { finish(false); return; }
          send("QUIT"); step = 9; break;
        case 9: // QUIT
          finish(code === 221); break;
      }
    }

    socket.on("data", (chunk: Buffer) => {
      buf += chunk.toString();
      let idx: number;
      while ((idx = buf.indexOf("\r\n")) !== -1) {
        const line = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        if (line) handle(line);
      }
    });
  });
}

// --- Email templates ---

export function emailReceived(url: string): string {
  return `<!DOCTYPE html><html><body style="font-family:sans-serif;max-width:560px;margin:40px auto;color:#1a1a1a">
<h2 style="margin-bottom:4px">Accessibility report received</h2>
<p style="color:#666;margin-top:0">gonzalezerik.com</p>
<p>Thank you for reporting an accessibility issue on <strong>${url}</strong>.</p>
<p>Our AI agent will investigate your report against WCAG 2.2 Level AA criteria and propose a fix if a genuine barrier is found. You&#39;ll hear back once the review is complete.</p>
<hr style="border:none;border-top:1px solid #eee;margin:24px 0">
<p style="font-size:12px;color:#999">This is an automated message from gonzalezerik.com.</p>
</body></html>`;
}

export function emailFixStarting(url: string, wcag: string): string {
  return `<!DOCTYPE html><html><body style="font-family:sans-serif;max-width:560px;margin:40px auto;color:#1a1a1a">
<h2 style="margin-bottom:4px">Accessibility fix approved &amp; deploying</h2>
<p style="color:#666;margin-top:0">gonzalezerik.com</p>
<p>A fix for the accessibility issue you reported on <strong>${url}</strong> has been reviewed and approved.</p>
<p><strong>WCAG criterion:</strong> ${wcag}</p>
<p>The fix is being deployed now. You&#39;ll receive a final confirmation once it&#39;s live and verified.</p>
<hr style="border:none;border-top:1px solid #eee;margin:24px 0">
<p style="font-size:12px;color:#999">This is an automated message from gonzalezerik.com.</p>
</body></html>`;
}

export function emailDeployed(url: string, wcag: string, verified: boolean): string {
  const status = verified
    ? "The fix is confirmed live — the page responded successfully."
    : "The fix was deployed. Live verification timed out; the site should be updated shortly.";
  return `<!DOCTYPE html><html><body style="font-family:sans-serif;max-width:560px;margin:40px auto;color:#1a1a1a">
<h2 style="margin-bottom:4px">Accessibility fix is live ✓</h2>
<p style="color:#666;margin-top:0">gonzalezerik.com</p>
<p>The accessibility issue you reported on <strong>${url}</strong> has been resolved.</p>
<p><strong>WCAG criterion addressed:</strong> ${wcag}</p>
<p>${status}</p>
<p>Thank you for helping make the site more accessible.</p>
<hr style="border:none;border-top:1px solid #eee;margin:24px 0">
<p style="font-size:12px;color:#999">This is an automated message from gonzalezerik.com.</p>
</body></html>`;
}

export function emailDismissed(url: string, reason: string): string {
  return `<!DOCTYPE html><html><body style="font-family:sans-serif;max-width:560px;margin:40px auto;color:#1a1a1a">
<h2 style="margin-bottom:4px">Accessibility report reviewed</h2>
<p style="color:#666;margin-top:0">gonzalezerik.com</p>
<p>Thank you for reporting an accessibility concern on <strong>${url}</strong>.</p>
<p>After review against WCAG 2.2 Level AA criteria, our agent determined that this report does not constitute a covered accessibility barrier:</p>
<blockquote style="border-left:3px solid #ddd;margin:16px 0;padding:8px 16px;color:#555">${reason}</blockquote>
<p>If you believe this is in error, please describe the issue in more detail.</p>
<hr style="border:none;border-top:1px solid #eee;margin:24px 0">
<p style="font-size:12px;color:#999">This is an automated message from gonzalezerik.com.</p>
</body></html>`;
}
