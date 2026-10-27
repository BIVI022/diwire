import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync, copyFileSync, readdirSync, existsSync } from "node:fs";
import { resolve, join } from "node:path";
const args = process.argv.slice(2);
const options = new Map();
for (let i = 0; i < args.length; i += 2) {
  if (!args[i]?.startsWith("--") || !args[i + 1]) throw new Error("Expected --project ID --checkout PATH --state-root PATH --provider ID --model ID --reasoning LEVEL");
  options.set(args[i], args[i + 1]);
}
for (const key of ["project", "checkout", "state-root", "provider", "model", "reasoning"]) if (!options.has("--" + key)) throw new Error("Missing --" + key);
const command = (bin, args) => execFileSync(bin, args, {encoding: "utf8", maxBuffer: 8 * 1024 * 1024}).trim();
const root = command("git", ["rev-parse", "--show-toplevel"]);
if (command("git", ["status", "--porcelain"])) throw new Error("Install from a clean committed worktree");
const revision = command("git", ["rev-parse", "HEAD"]);
const stateRoot = resolve(options.get("--state-root"));
const checkout = resolve(options.get("--checkout"));
const runtime = join(stateRoot, "runtime", revision);
const prompts = join(runtime, "prompts");
mkdirSync(prompts, {recursive: true});
const files = new Map([["tools/bb_perf_dispatch.py", "bb_perf_dispatch.py"]]);
for (const name of readdirSync(join(root, ".bb/automation/prompts"))) if (name.endsWith(".md")) files.set(".bb/automation/prompts/" + name, "prompts/" + name);
const fingerprints = {};
for (const [source, target] of files) {
  const content = readFileSync(join(root, source));
  const dest = join(runtime, target);
  if (existsSync(dest) && !readFileSync(dest).equals(content)) throw new Error("A pinned runtime copy was modified: " + dest);
  copyFileSync(join(root, source), dest);
  fingerprints[target] = createHash("sha256").update(content).digest("hex");
}
const config = {
  project_id: options.get("--project"), repository: "maksimzayats/diwire", checkout,
  prompt_directory: prompts, provider: options.get("--provider"), model: options.get("--model"), reasoning: options.get("--reasoning"),
  timezone: "Europe/Minsk", daily_time: "09:00", release_day: "Monday", release_time: "12:00",
  review_wait_seconds: 600, review_deadline_seconds: 86400, max_recovery_attempts: 2,
};
const configPath = join(stateRoot, "config.json");
const stateDir = join(stateRoot, "state");
const quote = s => "'" + s.replaceAll("'", "'\\''") + "'";
const scriptPath = join(stateRoot, "controller.sh");
writeFileSync(configPath, JSON.stringify(config, null, 2) + "\n", {mode: 0o600});
writeFileSync(scriptPath, "#!/usr/bin/env bash\nset -euo pipefail\nexec python3 " + [join(runtime, "bb_perf_dispatch.py"), "--config", configPath, "--state-dir", stateDir, "tick"].map(quote).join(" ") + "\n", {mode: 0o700});
const name = "DIWire: daily perf PRs and weekly patch releases";
const project = options.get("--project");
const all = JSON.parse(command("bb", ["automation", "list", "--project", project, "--json"]));
const matches = all.filter(item => item.name === name);
if (matches.length > 1) throw new Error("Duplicate pipeline schedules need reconciliation");
const baseArgs = ["--project", project, "--name", name, "--cron", "*/10 * * * *", "--timezone", "Europe/Minsk", "--script-file", scriptPath, "--timeout", "5m", "--working-directory", "project", "--json"];
let result;
if (matches.length) {
  command("bb", ["automation", "pause", matches[0].id, "--project", project, "--json"]);
  result = JSON.parse(command("bb", ["automation", "update", matches[0].id, ...baseArgs]));
} else result = JSON.parse(command("bb", ["automation", "create", "--disabled", ...baseArgs]));
const manifest = {installed_at: new Date().toISOString(), revision, runtime, config_path: configPath, state_dir: stateDir, script_path: scriptPath, fingerprints, automation: result};
writeFileSync(join(stateRoot, "installation.json"), JSON.stringify(manifest, null, 2) + "\n", {mode: 0o600});
process.stdout.write(JSON.stringify(manifest, null, 2) + "\n");
