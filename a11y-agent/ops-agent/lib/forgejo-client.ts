const FORGEJO_URL = process.env.FORGEJO_URL ?? "https://forgejo.example.com";
const FORGEJO_TOKEN = process.env.FORGEJO_TOKEN ?? "";

function headers() {
  return {
    Authorization: `token ${FORGEJO_TOKEN}`,
    "Content-Type": "application/json",
  };
}

export async function fetchForgejoFile(
  owner: string,
  repo: string,
  path: string,
  ref = "main"
): Promise<{ content: string; sha: string } | null> {
  const url = `${FORGEJO_URL}/api/v1/repos/${owner}/${repo}/contents/${path}?ref=${ref}`;
  const res = await fetch(url, { headers: headers() });
  if (!res.ok) return null;
  const data = await res.json();
  const content = Buffer.from(data.content, "base64").toString("utf-8");
  return { content, sha: data.sha };
}

export async function createOrUpdateForgejoFile(
  owner: string,
  repo: string,
  path: string,
  content: string,
  message: string
): Promise<boolean> {
  const url = `${FORGEJO_URL}/api/v1/repos/${owner}/${repo}/contents/${path}`;

  // Get current SHA if file exists
  const existing = await fetch(url, { headers: headers() });
  let sha: string | undefined;
  if (existing.ok) {
    const data = await existing.json();
    sha = data.sha;
  }

  const body: Record<string, string> = {
    message,
    content: Buffer.from(content).toString("base64"),
  };
  if (sha) body.sha = sha;

  const res = await fetch(url, {
    method: sha ? "PUT" : "POST",
    headers: headers(),
    body: JSON.stringify(body),
  });
  return res.ok;
}
