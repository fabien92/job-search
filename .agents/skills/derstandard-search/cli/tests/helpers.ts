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
  const proc = Bun.spawn(["bun", "run", "--preload", preload, CLI_PATH, ...args], {
    stdout: "pipe",
    stderr: "pipe",
  });
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ]);
  return { stdout: stdout.trim(), stderr: stderr.trim(), exitCode };
}

/**
 * Run the real CLI in a fresh process with `fetch` replaced by a preload that answers
 * only https://jobs.derstandard.at<allowedPath> with `fixture`, read from disk; anything
 * else throws before reaching the network. No server, no port (JobBot rule: tests
 * without network and without ports). Requests are logged to a file and returned.
 */
export async function runWithFixture(
  args: string[],
  fixture: string,
  allowedPath: string,
  contentType: string,
): Promise<{ result: CLIResult; requests: URL[] }> {
  const dir = mkdtempSync(join(tmpdir(), "derstandard-fixture-"));
  const preload = join(dir, "fetch.ts");
  const log = join(dir, "requests.log");
  writeFileSync(log, "");
  writeFileSync(preload, `
    import { appendFileSync, readFileSync } from "node:fs";
    globalThis.fetch = (async (input) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      appendFileSync(${JSON.stringify(log)}, url.href + "\\n");
      if (url.origin !== "https://jobs.derstandard.at" || url.pathname !== ${JSON.stringify(allowedPath)}) {
        throw new Error("Unexpected fixture request: " + url);
      }
      const body = readFileSync(${JSON.stringify(join(import.meta.dir, "fixtures", fixture))});
      return new Response(body, { status: 200, headers: { "Content-Type": ${JSON.stringify(contentType)} } });
    });
  `);
  try {
    const result = await runCLI(args, preload);
    const requests = readFileSync(log, "utf8").split("\n").filter(Boolean).map((u) => new URL(u));
    return { result, requests };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

export function parseJSON<T = unknown>(result: CLIResult): T {
  if (result.exitCode !== 0) {
    throw new Error(`CLI exited with code ${result.exitCode}. stderr: ${result.stderr}`);
  }
  try {
    return JSON.parse(result.stdout) as T;
  } catch {
    throw new Error(`Failed to parse JSON. stdout: ${result.stdout}\nstderr: ${result.stderr}`);
  }
}
