/**
 * Dependency-free SMTP email sender using Node.js built-in net/tls.
 * Supports plain SMTP (port 25, no auth) and direct TLS (port 465).
 * Env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, SMTP_SECURE
 * SMTP_SECURE defaults to "true" (port 465 TLS). Set to "false" for plain.
 */
import * as net from "net";
import * as tls from "tls";

const host   = () => process.env.SMTP_HOST ?? "";
const port   = () => parseInt(process.env.SMTP_PORT ?? "465");
const user   = () => process.env.SMTP_USER ?? "";
const pass   = () => process.env.SMTP_PASS ?? "";
const from   = () => process.env.SMTP_FROM ?? "noreply@gonzalezerik.com";
const secure = () => process.env.SMTP_SECURE !== "false";

export async function sendEmail(to: string, subject: string, html: string): Promise<boolean> {
  if (!host() || !to.includes("@")) return false;

  return new Promise((resolve) => {
    const socket = secure()
      ? (tls.connect({ host: host(), port: port(), rejectUnauthorized: false }) as unknown as net.Socket)
      : net.createConnection({ host: host(), port: port() });

    let buf = "";
    let step = 0;
    let settled = false;
    const finish = (ok: boolean) => { if (settled) return; settled = true; socket.destroy(); resolve(ok); };

    socket.setTimeout(15_000);
    socket.on("timeout", () => finish(false));
    socket.on("error",   () => finish(false));

    const send = (line: string) => socket.write(line + "\r\n");

    const msgBody = [
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
      if (line[3] === "-") return; // multi-line continuation
      switch (step) {
        case 0: // server greeting
          if (code !== 220) { finish(false); return; }
          send("EHLO mission-control"); step = 1; break;
        case 1: // EHLO response
          if (code !== 250) { finish(false); return; }
          if (user()) { send("AUTH LOGIN"); step = 2; }
          else { send(`MAIL FROM:<${from()}>`); step = 5; }
          break;
        case 2: // AUTH LOGIN - username prompt
          if (code !== 334) { finish(false); return; }
          send(Buffer.from(user()).toString("base64")); step = 3; break;
        case 3: // AUTH LOGIN - password prompt
          if (code !== 334) { finish(false); return; }
          send(Buffer.from(pass()).toString("base64")); step = 4; break;
        case 4: // AUTH success
          if (code !== 235) { finish(false); return; }
          send(`MAIL FROM:<${from()}>`); step = 5; break;
        case 5: // MAIL FROM
          if (code !== 250) { finish(false); return; }
          send(`RCPT TO:<${to}>`); step = 6; break;
        case 6: // RCPT TO
          if (code !== 250) { finish(false); return; }
          send("DATA"); step = 7; break;
        case 7: // DATA prompt
          if (code !== 354) { finish(false); return; }
          socket.write(msgBody + "\r\n"); step = 8; break;
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

// ----- HTML email templates -----

export function emailReceived(url: string): string {
  return `<!DOCTYPE html><html><body style="font-family:sans-serif;max-width:560px;margin:40px auto;color:#1a1a1a">
<h2>Accessibility report received</h2>
<p>Thank you for reporting an accessibility issue on <strong>${url}</strong>.</p>
<p>Our AI agent will review your report against WCAG 2.2 Level AA criteria and propose a code fix if a genuine barrier is found. You will hear back once the review is complete.</p>
<hr style="border:none;border-top:1px solid #eee;margin:24px 0">
<p style="font-size:12px;color:#999">Automated message · gonzalezerik.com</p>
</body></html>`;
}

export function emailFixStarting(url: string, wcag: string): string {
  return `<!DOCTYPE html><html><body style="font-family:sans-serif;max-width:560px;margin:40px auto;color:#1a1a1a">
<h2>Accessibility fix approved &amp; deploying</h2>
<p>A fix for the issue you reported on <strong>${url}</strong> has been reviewed and approved.</p>
<p><strong>WCAG criterion:</strong> ${wcag}</p>
<p>The fix is building and deploying now. You will receive a final confirmation once it is live.</p>
<hr style="border:none;border-top:1px solid #eee;margin:24px 0">
<p style="font-size:12px;color:#999">Automated message · gonzalezerik.com</p>
</body></html>`;
}

export function emailDeployed(url: string, wcag: string, verified: boolean): string {
  const note = verified
    ? "Confirmed live — the page responded successfully."
    : "Deployed. Live verification timed out; the site should be updated momentarily.";
  return `<!DOCTYPE html><html><body style="font-family:sans-serif;max-width:560px;margin:40px auto;color:#1a1a1a">
<h2>Accessibility fix is live</h2>
<p>The issue you reported on <strong>${url}</strong> has been resolved.</p>
<p><strong>WCAG criterion addressed:</strong> ${wcag}</p>
<p>${note}</p>
<p>Thank you for helping make the site more accessible.</p>
<hr style="border:none;border-top:1px solid #eee;margin:24px 0">
<p style="font-size:12px;color:#999">Automated message · gonzalezerik.com</p>
</body></html>`;
}

export function emailDismissed(url: string, reason: string): string {
  return `<!DOCTYPE html><html><body style="font-family:sans-serif;max-width:560px;margin:40px auto;color:#1a1a1a">
<h2>Accessibility report reviewed</h2>
<p>Thank you for reporting a concern on <strong>${url}</strong>.</p>
<p>After review against WCAG 2.2 Level AA criteria, our agent found that this report does not constitute a covered accessibility barrier:</p>
<blockquote style="border-left:3px solid #ddd;margin:16px 0;padding:8px 16px;color:#555">${reason}</blockquote>
<p>If you believe this is in error, please describe the issue in more detail.</p>
<hr style="border:none;border-top:1px solid #eee;margin:24px 0">
<p style="font-size:12px;color:#999">Automated message · gonzalezerik.com</p>
</body></html>`;
}
