import { join } from "path";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";

const CLI_PATH = join(import.meta.dir, "../src/cli.ts");
const NO_NETWORK = join(import.meta.dir, "no-network.ts");

export interface CLIResult {
  stdout: string;
  stderr: string;
  exitCode: number;
}

export async function runCLI(args: string[], preload = NO_NETWORK): Promise<CLIResult> {
  const proc = Bun.spawn(["bun", "run", "--preload", preload, CLI_PATH, ...args], { stdout: "pipe", stderr: "pipe" });
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ]);
  return { stdout: stdout.trim(), stderr: stderr.trim(), exitCode };
}

export interface LoggedRequest {
  method: string;
  url: string;
  body: any;
  userAgent: string | null;
}

/**
 * Run the real CLI with `fetch` replaced by a preload that answers only
 * <method> https://careers.un.org<allowedPath> with `fixture` read from disk; anything else
 * throws before reaching the network. No server, no port (JobBot rule). Requests are logged.
 */
export async function runWithFixture(
  args: string[],
  fixture: string,
  method: "GET" | "POST",
  allowedPath: string,
): Promise<{ result: CLIResult; requests: LoggedRequest[] }> {
  const dir = mkdtempSync(join(tmpdir(), "un-careers-fixture-"));
  const preload = join(dir, "fetch.ts");
  const log = join(dir, "requests.log");
  writeFileSync(log, "");
  writeFileSync(preload, `
    import { appendFileSync, readFileSync } from "node:fs";
    globalThis.fetch = (async (input, init = {}) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      const m = (init.method || "GET").toUpperCase();
      const h = new Headers(init.headers || {});
      appendFileSync(${JSON.stringify(log)}, JSON.stringify({ method: m, url: url.href, body: init.body ? JSON.parse(init.body) : null, userAgent: h.get("user-agent") }) + "\\n");
      if (url.origin !== "https://careers.un.org" || url.pathname !== ${JSON.stringify(allowedPath)} || m !== ${JSON.stringify(method)}) {
        throw new Error("Unexpected fixture request: " + m + " " + url);
      }
      const body = readFileSync(${JSON.stringify(join(import.meta.dir, "fixtures", fixture))});
      return new Response(body, { status: 200, headers: { "Content-Type": "application/json" } });
    });
  `);
  try {
    const result = await runCLI(args, preload);
    const requests = readFileSync(log, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
    return { result, requests };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

export function parseJSON<T = unknown>(result: CLIResult): T {
  if (result.exitCode !== 0) throw new Error(`CLI exited with code ${result.exitCode}. stderr: ${result.stderr}`);
  try {
    return JSON.parse(result.stdout) as T;
  } catch {
    throw new Error(`Failed to parse JSON. stdout: ${result.stdout}\nstderr: ${result.stderr}`);
  }
}
