import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const webRoot = fileURLToPath(new URL('..', import.meta.url));
const source = path.resolve(webRoot, process.env.COCONERD_BACKEND_SOURCE || '..');
const bundledPython = path.join(source, '.venv/bin/python');
const python = process.env.COCONERD_PYTHON || (existsSync(bundledPython) ? bundledPython : 'python3');
const testing = process.argv[2] === 'test';
const args = testing
  ? ['-m', 'pytest', 'tests/test_bridge.py', '-q', '-p', 'no:cacheprovider', '--basetemp=.cache/pytest']
  : ['-m', 'uvicorn', 'bridge.app:application', '--factory', '--host', '127.0.0.1', '--port', process.env.COCONERD_BRIDGE_PORT || '8001'];
const env = { ...process.env, PYTHONPATH: [webRoot, source].join(path.delimiter), PYTHONDONTWRITEBYTECODE: '1' };
if (testing) env.COCONERD_DATABASE_URL = 'sqlite+aiosqlite:///:memory:';
const child = spawn(python, args, { cwd: webRoot, stdio: 'inherit', env });
child.on('error', () => { console.error('Python/backend dependencies unavailable. See README.md.'); process.exitCode = 1; });
child.on('exit', code => { process.exitCode = code ?? 1; });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
