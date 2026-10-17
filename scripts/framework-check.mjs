#!/usr/bin/env node
// Framework structural drift checker (shared across projects).
// Node stdlib only. Reads `framework.config.json` at the project root.
// It checks deterministic structure; it is not semantic review.
// Usage: node scripts/framework-check.mjs [--root <dir>]
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

function resolveRoot() {
  const i = process.argv.indexOf('--root');
  if (i !== -1) {
    const v = process.argv[i + 1];
    if (!v) { console.log('FAIL: --root requires a directory'); process.exit(1); }
    return path.resolve(v);
  }
  return path.dirname(path.dirname(fileURLToPath(import.meta.url)));
}

const ROOT = resolveRoot();
const errors = [];
const fail = (message) => errors.push(message);
const exists = (rel) => fs.existsSync(path.join(ROOT, rel));
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
const readJson = (rel) => JSON.parse(read(rel));

function finish() {
  for (const e of errors) console.log(`FAIL: ${e}`);
  process.exit(1);
}

const CONFIG = 'framework.config.json';
if (!exists(CONFIG)) { fail(`missing ${CONFIG}`); finish(); }

let config;
try { config = readJson(CONFIG); } catch (e) { fail(`${CONFIG}: invalid JSON (${e.message})`); finish(); }

const isStringArray = (v) => Array.isArray(v) && v.every((x) => typeof x === 'string' && x.length > 0);
const ROLE_NAMES = ['product', 'orchestrator'];
const ALL_ROLE_NAMES = ['product', 'orchestrator', 'implementer'];
const EXECUTION_MODES = ['interactive', 'local', 'ci'];

if (config === null || typeof config !== 'object' || Array.isArray(config)) fail(`${CONFIG}: must be a JSON object`);
else {
  if (typeof config.frameworkVersion !== 'string' || !config.frameworkVersion) fail(`${CONFIG}: frameworkVersion must be a non-empty string`);
  if (!isStringArray(config.adapters)) fail(`${CONFIG}: adapters must be an array of strings`);
  if ('requiredFiles' in config && !isStringArray(config.requiredFiles)) fail(`${CONFIG}: requiredFiles must be an array of strings`);
  if ('requiredTokens' in config) {
    const t = config.requiredTokens;
    if (t === null || typeof t !== 'object' || Array.isArray(t) || !Object.values(t).every(isStringArray)) {
      fail(`${CONFIG}: requiredTokens must be an object mapping file -> array of strings`);
    }
  }
  for (const key of ['taskDir', 'decisionDir']) {
    if (key in config && (typeof config[key] !== 'string' || !config[key])) fail(`${CONFIG}: ${key} must be a non-empty string`);
  }
  if ('governance' in config) {
    const g = config.governance;
    if (g === null || typeof g !== 'object' || Array.isArray(g)) fail(`${CONFIG}: governance must be an object`);
    else {
      if ('taskAuthorization' in g && !['task', 'boundary'].includes(g.taskAuthorization)) fail(`${CONFIG}: governance.taskAuthorization must be task or boundary`);
      if ('maxParallelImplementers' in g && (!Number.isInteger(g.maxParallelImplementers) || g.maxParallelImplementers < 1 || g.maxParallelImplementers > 3)) fail(`${CONFIG}: governance.maxParallelImplementers must be an integer from 1 to 3`);
    }
  }
  if ('agents' in config) {
    const agents = config.agents;
    if (agents === null || typeof agents !== 'object' || Array.isArray(agents)) {
      fail(`${CONFIG}: agents must be an object`);
    } else {
      for (const role of ROLE_NAMES) {
        if (role in agents && (typeof agents[role] !== 'string' || !agents[role])) {
          fail(`${CONFIG}: agents.${role} must be a non-empty string`);
        }
      }
      for (const key of Object.keys(agents)) {
        if (!ROLE_NAMES.includes(key)) fail(`${CONFIG}: unknown agent binding: ${key}`);
      }
    }
  }
}
if (errors.length) finish();

const adapters = config.adapters;
const extraFiles = config.requiredFiles ?? [];
const requiredTokens = config.requiredTokens ?? {};
const taskDir = (config.taskDir ?? 'docs/tasks').replace(/\/+$/, '');
const decisionDir = (config.decisionDir ?? 'docs/decisions').replace(/\/+$/, '');

if (new Set(adapters).size !== adapters.length) fail(`${CONFIG}: adapters must not contain duplicates`);

const availableAdapterIds = exists('adapters')
  ? fs.readdirSync(path.join(ROOT, 'adapters'), { withFileTypes: true })
      .filter((e) => e.isDirectory() && exists(`adapters/${e.name}/adapter.json`))
      .map((e) => e.name)
  : [];

const descriptors = new Map();
for (const id of adapters) {
  if (!availableAdapterIds.includes(id)) {
    fail(`${CONFIG}: unknown adapter: ${id} (missing adapters/${id}/adapter.json)`);
    continue;
  }
  const rel = `adapters/${id}/adapter.json`;
  let d;
  try { d = readJson(rel); } catch (e) { fail(`${rel}: invalid JSON (${e.message})`); continue; }
  descriptors.set(id, d);
  if (d.schemaVersion !== '1') fail(`${rel}: schemaVersion must be 1`);
  if (d.id !== id) fail(`${rel}: id must match adapter directory ${id}`);
  if (typeof d.displayName !== 'string' || !d.displayName) fail(`${rel}: displayName must be a non-empty string`);
  if (!isStringArray(d.roles)) fail(`${rel}: roles must be an array of strings`);
  else {
    if (new Set(d.roles).size !== d.roles.length) fail(`${rel}: roles must not contain duplicates`);
    for (const role of d.roles) if (!ALL_ROLE_NAMES.includes(role)) fail(`${rel}: unknown role: ${role}`);
  }
  if (!isStringArray(d.execution)) fail(`${rel}: execution must be an array of strings`);
  else for (const mode of d.execution) if (!EXECUTION_MODES.includes(mode)) fail(`${rel}: invalid execution mode: ${mode}`);
  const caps = d.capabilities;
  const capNames = ['readRepository', 'writeRepository', 'shell', 'git', 'pullRequest'];
  if (caps === null || typeof caps !== 'object' || Array.isArray(caps)) fail(`${rel}: capabilities must be an object`);
  else {
    for (const name of capNames) if (typeof caps[name] !== 'boolean') fail(`${rel}: capabilities.${name} must be boolean`);
  }
}

const boundAgents = config.agents ?? {};
const governance = config.governance ?? {};
const taskAuthorization = governance.taskAuthorization ?? 'task';
const maxParallelImplementers = governance.maxParallelImplementers ?? 1;
for (const role of ROLE_NAMES) {
  if (!(role in boundAgents)) continue;
  const adapterId = boundAgents[role];
  if (!adapters.includes(adapterId)) {
    fail(`${CONFIG}: agents.${role} references disabled adapter: ${adapterId}`);
    continue;
  }
  const descriptor = descriptors.get(adapterId);
  if (descriptor && !descriptor.roles.includes(role)) {
    fail(`${CONFIG}: agents.${role} adapter ${adapterId} does not support role ${role}`);
  }
}

// ---- Required files -----------------------------------------------------
const coreFiles = [
  'AGENTS.md',
  'docs/ai/workflow.md',
  'docs/ai/execution-profiles.md',
  'docs/ai/project-profile.md',
  'docs/ai/framework-history.md',
  'docs/workflow/current-state.md',
  'docs/tasks/_template.md',
  'FRAMEWORK_ADOPTION.md',
  'docs/ai/agent-adapter-contract.md',
  'docs/ai/adapter-descriptor.schema.json',
];
const adapterFiles = {
  'claude-code': ['CLAUDE.md', '.claude/rules/execution.md', '.claude/agents/implementer.md'],
  copilot: ['.github/copilot-instructions.md', '.github/agents/implementer.agent.md'],
  codex: [],
  chatgpt: [],
};
const required = [...new Set([
  CONFIG,
  ...coreFiles,
  ...adapters.flatMap((a) => adapterFiles[a] ?? []),
  ...extraFiles,
])];
for (const rel of required) if (!exists(rel)) fail(`missing required file: ${rel}`);

// ---- Status / metadata --------------------------------------------------
function metadata(rel, key) {
  const line = read(rel).split('\n').find((x) => new RegExp(`^\\|\\s*${key}\\s*\\|`).test(x.trim()));
  return line ? line.split('|')[2].trim() : null;
}
const status = (rel) => metadata(rel, 'Status');

if (maxParallelImplementers < 1 || maxParallelImplementers > 3) fail(`${CONFIG}: governance.maxParallelImplementers must be an integer from 1 to 3`);

for (const rel of ['docs/ai/workflow.md', 'docs/ai/execution-profiles.md', 'docs/ai/project-profile.md', 'docs/ai/framework-history.md', 'docs/ai/agent-adapter-contract.md']) {
  if (exists(rel) && status(rel) !== 'CURRENT') fail(`${path.basename(rel)} must be CURRENT`);
}
if (exists('docs/workflow/current-state.md') && status('docs/workflow/current-state.md') !== 'OPERATIONAL STATE — NOT AUTHORITY') {
  fail('current-state.md has wrong operational status');
}

// ---- Version <-> config <-> history ------------------------------------
if (exists('docs/ai/workflow.md')) {
  const version = metadata('docs/ai/workflow.md', 'Version');
  if (!version) fail('workflow.md missing metadata row: | Version | ... |');
  else {
    if (version !== config.frameworkVersion) fail(`workflow.md Version ${version} does not match ${CONFIG} frameworkVersion ${config.frameworkVersion}`);
    if (exists('docs/ai/framework-history.md')) {
      const heading = `## v${version}`;
      const found = read('docs/ai/framework-history.md').split('\n').some((x) => x === heading || x.startsWith(`${heading} `));
      if (!found) fail(`framework-history.md missing entry for workflow Version ${version} (expected heading: ${heading})`);
    }
  }
}

// ---- Adoption record ----------------------------------------------------
if (exists('FRAMEWORK_ADOPTION.md')) {
  const a = read('FRAMEWORK_ADOPTION.md');
  for (const token of ['Adopted', 'Adapted', 'Not adopted']) if (!a.includes(token)) fail(`FRAMEWORK_ADOPTION.md missing section: ${token}`);
}

// ---- Adapter checks -----------------------------------------------------
if (adapters.includes('claude-code')) {
  if (exists('CLAUDE.md')) {
    const body = read('CLAUDE.md').replace(/<!--[\s\S]*?-->/g, '').trim();
    if (body !== '@AGENTS.md') fail('CLAUDE.md must be a minimal AGENTS.md bridge');
  }
  if (exists('.claude/rules/execution.md') && !read('.claude/rules/execution.md').includes('@../../docs/workflow/current-state.md')) {
    fail('.claude/rules/execution.md must import current-state.md');
  }
}

// ---- Project-specific required tokens ----------------------------------
for (const [rel, tokens] of Object.entries(requiredTokens)) {
  if (!exists(rel)) { fail(`requiredTokens: file not found: ${rel}`); continue; }
  const content = read(rel);
  for (const token of tokens) if (!content.includes(token)) fail(`${rel}: missing required token: ${token}`);
}

// ---- Unfilled template markers -----------------------------------------
for (const rel of required) {
  if (!exists(rel) || fs.statSync(path.join(ROOT, rel)).isDirectory()) continue;
  if (/<!--[\s]*FILL:/.test(read(rel))) fail(`${rel}: unfilled template marker: <!-- FILL: ... -->`);
}

// ---- Task contracts -----------------------------------------------------
const taskFields = {
  'Status': ['DRAFT', 'APPROVED', 'IN_PROGRESS', 'READY'],
  'Type': null,
  'Change class': ['S1', 'S2'],
  'Owner': null,
  'Execution profile': ['single-agent', 'dual-agent'],
  'Implementation authorized': ['YES', 'NO'],
};
const taskSections = ['Goal', 'Scope', 'Acceptance Criteria', 'Required verification'];
const listMd = (dir) => (exists(dir) && fs.statSync(path.join(ROOT, dir)).isDirectory()
  ? fs.readdirSync(path.join(ROOT, dir)).filter((f) => f.endsWith('.md')).sort()
  : []);
const tasks = listMd(taskDir).filter((f) => f !== '_template.md');
for (const file of tasks) {
  const rel = `${taskDir}/${file}`;
  const lines = read(rel).split('\n');
  for (const [field, allowed] of Object.entries(taskFields)) {
    const line = lines.find((x) => x.startsWith(`- ${field}:`));
    const value = line ? line.slice(`- ${field}:`.length).trim() : '';
    if (!value) fail(`${rel}: missing field: ${field}`);
    else if (allowed && !allowed.includes(value)) fail(`${rel}: invalid ${field}: ${value}`);
  }
  const authorizationLine = lines.find((x) => x.startsWith('- Authorization mode:'));
  const authorizationMode = authorizationLine?.slice('- Authorization mode:'.length).trim();
  if (authorizationMode && !['task', 'boundary'].includes(authorizationMode)) fail(`${rel}: invalid Authorization mode: ${authorizationMode}`);
  if (taskAuthorization === 'boundary' && authorizationMode !== 'boundary') fail(`${rel}: boundary governance requires Authorization mode: boundary`);
  if (authorizationMode === 'boundary') {
    const sourceLine = lines.find((x) => x.startsWith('- Authorization source:'));
    const source = sourceLine?.slice('- Authorization source:'.length).trim();
    if (!source || source.startsWith('<')) fail(`${rel}: boundary authorization requires Authorization source`);
    if (taskAuthorization !== 'boundary') fail(`${rel}: task uses boundary authorization but ${CONFIG} governance.taskAuthorization is ${taskAuthorization}`);
  }
  if (authorizationMode === 'task' && taskAuthorization === 'boundary') {
    // Explicit per-task authorization remains allowed for legacy/exception tasks, but boundary is the project default.
  }
  const profileLine = lines.find((x) => x.startsWith('- Execution profile:'));
  const profile = profileLine?.slice('- Execution profile:'.length).trim();
  if (profile === 'dual-agent') {
    const implLine = lines.find((x) => x.startsWith('- Implementer:'));
    const impl = implLine?.slice('- Implementer:'.length).trim().split(/\s+/)[0];
    if (!impl) fail(`${rel}: dual-agent task missing field: Implementer`);
    else if (!adapters.includes(impl)) fail(`${rel}: Implementer ${impl} is not an enabled adapter`);
    else if (!descriptors.get(impl)?.roles.includes('implementer')) fail(`${rel}: Implementer ${impl} does not support role implementer`);
  }
  for (const section of taskSections) if (!lines.includes(`## ${section}`)) fail(`${rel}: missing section: ${section}`);
}

// ---- Decision records ---------------------------------------------------
const decisionStatuses = ['PROPOSED', 'ACCEPTED', 'SUPERSEDED'];
const decisions = listMd(decisionDir);
for (const file of decisions) {
  const rel = `${decisionDir}/${file}`;
  const value = status(rel);
  if (!value) fail(`${rel}: missing metadata row: | Status | ... |`);
  else if (!decisionStatuses.some((s) => value.startsWith(s))) fail(`${rel}: invalid Status: ${value} (must start with ${decisionStatuses.join(', ')})`);
}

if (errors.length) finish();

for (const rel of required) console.log(`PASS: ${rel}`);
for (const file of tasks) console.log(`PASS: task contract ${taskDir}/${file}`);
for (const file of decisions) console.log(`PASS: decision record ${decisionDir}/${file}`);
for (const id of adapters) console.log(`PASS: adapter descriptor adapters/${id}/adapter.json`);
console.log('PASS: framework structure');
