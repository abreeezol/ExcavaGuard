import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const mode = process.argv[2] ?? 'all';
if (!['pit', 'tunnel', 'all'].includes(mode)) throw new Error('Use pit, tunnel, or all.');
const root = process.cwd();
const temporary = mkdtempSync(join(tmpdir(), 'excavaguard-data-tests-'));
const environment = { ...process.env, EXCAVAGUARD_ACCESS_PASSWORD: '', EXCAVAGUARD_STORAGE_PROVIDER: 'local', EXCAVAGUARD_PROJECT_ID: '11111111-1111-4111-8111-111111111111' };
for (const key of Object.keys(environment)) if (key.startsWith('EXCAVAGUARD_TEST_')) environment[key] = '0';
for (const [key, name] of Object.entries({ EXCAVAGUARD_ACCESS_FILE: 'access.json', EXCAVAGUARD_UPLOAD_ROOT: 'uploads',
  EXCAVAGUARD_RUN_ROOT: 'runs', EXCAVAGUARD_STANDARD_CHANGES_ROOT: 'changes',
  EXCAVAGUARD_PROJECT_STANDARDS_ROOT: 'standards', EXCAVAGUARD_PROJECT_CONTEXT_ROOT: 'context' })) {
  environment[key] = join(temporary, name);
}
const python = process.env.EXCAVAGUARD_PYTHON || [resolve('.venv/bin/python'), resolve('.venv/Scripts/python.exe')].find(existsSync) || 'python3';
environment.EXCAVAGUARD_PYTHON = python;
const pit = ['tests/upload-and-run.test.ts', 'tests/wide-upload-and-run.test.ts', 'tests/report-skills.test.ts'];
const tunnel = ['tests/tunnel-10min-acceptance.test.ts', 'tests/high-frequency-model-context.test.ts',
  'tests/tunnel-report-template.test.ts', 'tests/engineer-feedback-semantics.test.ts'];
const steps = [];
async function run(label, executable, args) {
  console.info(`\n${label}`);
  const started = Date.now();
  const code = await new Promise((resolveCode, reject) => {
    const child = spawn(executable, args, { cwd: root, env: environment, stdio: 'inherit' });
    child.once('error', reject);
    child.once('close', (code) => resolveCode(code ?? 1));
  });
  steps.push({ label, exit_code: code, duration_ms: Date.now() - started });
  if (code) throw new Error(`${label} failed (${code}).`);
}
try {
  if (mode !== 'tunnel') await run('Pit inputs, current weekly report and 27 scenarios', python, ['tools/test/check_pit_test_data.py']);
  if (mode !== 'pit') await run('Versioned tunnel knowledge index', process.execPath, ['tools/knowledge/check-index.mjs']);
  if (mode !== 'pit') await run('Tunnel checksums, 10-minute timeline and equivalent inputs', python, ['tools/test/check_tunnel_test_data.py']);
  const suites = mode === 'pit' ? pit : mode === 'tunnel' ? tunnel : [...pit, ...tunnel];
  await run('Isolated upload, analysis, report and audit regressions', process.execPath, ['node_modules/vitest/vitest.mjs', 'run', ...suites]);
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  const destination = resolve('var/acceptance/test-data');
  mkdirSync(destination, { recursive: true });
  writeFileSync(join(destination, `${mode}-summary.json`), JSON.stringify({ mode, passed: !process.exitCode, external_services_called: false, steps }, null, 2) + '\n');
  rmSync(temporary, { recursive: true, force: true });
}
