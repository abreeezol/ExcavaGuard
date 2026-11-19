import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { it } from 'vitest';

it('隧道报告五节模板、规范条文与来源追溯及篡改拦截', () => {
  execFileSync(process.env.EXCAVAGUARD_PYTHON || resolve('.venv/bin/python'),
    ['-B', 'tests/test_tunnel_report_template.py'], { stdio: 'pipe' });
});
