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
    env: { ...process.env, HAYS_CLI_DELAY_MS: "0" },
  });
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ]);
  return { stdout: stdout.trim(), stderr: stderr.trim(), exitCode };
}

/** One answered path: the fixture file, and the URL the response reports (to emulate a redirect). */
export interface Route {
  fixture: string;
  finalPath?: string;
  status?: number;
}

/**
 * Run the real CLI in a fresh process with `fetch` replaced by a preload that answers only
 * https://www.hays.at<path+query> for the given routes, from fixture files on disk; anything
 * else throws before reaching the network. No server, no port (JobBot rule: tests without
 * network and without ports). Requests are logged to a file and returned.
 */
export async function runWithFixtures(
  args: string[],
  routes: Record<string, Route>,
): Promise<{ result: CLIResult; requests: URL[] }> {
  const dir = mkdtempSync(join(tmpdir(), "hays-fixture-"));
  const preload = join(dir, "fetch.ts");
  const log = join(dir, "requests.log");
  writeFileSync(log, "");
  writeFileSync(preload, `
    import { appendFileSync, readFileSync } from "node:fs";
    const routes = ${JSON.stringify(routes)};
    const fixtures = ${JSON.stringify(join(import.meta.dir, "fixtures"))};
    globalThis.fetch = (async (input) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      appendFileSync(${JSON.stringify(log)}, url.href + "\\n");
      const route = url.origin === "https://www.hays.at" ? routes[url.pathname + url.search] : undefined;
      if (!route) throw new Error("Unexpected fixture request: " + url);
      const body = route.fixture ? readFileSync(fixtures + "/" + route.fixture) : "";
      const res = new Response(body, { status: route.status ?? 200, headers: { "Content-Type": "text/html" } });
      Object.defineProperty(res, "url", { value: "https://www.hays.at" + (route.finalPath ?? url.pathname + url.search) });
      return res;
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
