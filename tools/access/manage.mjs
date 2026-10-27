// Local administrator tool. Never uploads credentials or calls Supabase.
import { randomBytes, randomUUID } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync, renameSync, rmSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { accessDirectorySchema, projectRoleSchema } from '../../src/contracts/project-access.ts';
import { hashPassword } from '../../src/server/auth/password.ts';

const [command, ...args] = process.argv.slice(2);
const options = {};
for (let i = 0; i < args.length; i += 2) {
  if (!args[i].startsWith('--') || !args[i + 1]) throw new Error('参数使用 --名称 值。');
  options[args[i].slice(2)] = args[i + 1];
}
const path = resolve(process.env.EXCAVAGUARD_ACCESS_FILE || 'var/access/directory.json');
if (!['init', 'add-user', 'grant', 'revoke', 'disable-user', 'set-password', 'list'].includes(command)) {
  console.info('Commands: init/add-user --username USER --name NAME; grant --username USER --project UUID --role admin|reviewer|engineer|viewer; revoke; disable-user; set-password (EXCAVAGUARD_NEW_PASSWORD); list.');
  process.exit(1);
}
mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
const lock = `${path}.lock`;
mkdirSync(lock);
const temporary = `${path}.${randomUUID()}.tmp`;
try {
  const defaultId = process.env.EXCAVAGUARD_PROJECT_ID?.trim() || '11111111-1111-4111-8111-111111111111';
  const directory = accessDirectorySchema.parse(existsSync(path) ? JSON.parse(readFileSync(path, 'utf8')) : {
    version: 1, session_secret: randomBytes(32).toString('hex'), users: [],
    projects: [{ id: defaultId, name: process.env.EXCAVAGUARD_PROJECT_NAME || '默认工程', active: true }],
    memberships: [{ user_id: 'local-operator', project_id: defaultId, role: 'admin' }],
  });
  const username = options.username?.trim().toLowerCase();
  if (command === 'list') {
    console.info(JSON.stringify({ users: directory.users.map(({ id, username, name, disabled, is_admin }) => ({ id, username, name, disabled, is_admin })), projects: directory.projects, memberships: directory.memberships }, null, 2));
  } else {
    if (command === 'init' || command === 'add-user') {
      if (!username || !/^[a-z0-9_.-]{2,80}$/.test(username)) throw new Error('请提供合法 --username。');
      if (command === 'init' && directory.users.length) throw new Error('已存在独立账号，请使用 add-user。');
      if (directory.users.some(u => u.username === username)) throw new Error('账号已存在。');
      const password = process.env.EXCAVAGUARD_NEW_PASSWORD || randomBytes(18).toString('base64url');
      const user = { id: randomUUID(), username, name: options.name || username, password_hash: hashPassword(password), disabled: false, is_admin: command === 'init' || options.admin === 'true' };
      directory.users.push(user);
      if (command === 'init') {
        const legacy = directory.memberships.filter(m => m.user_id === 'local-operator');
        directory.memberships = [...directory.memberships.filter(m => m.user_id !== 'local-operator'),
          ...legacy.map(m => ({ ...m, user_id: user.id }))];
        if (!legacy.length && directory.projects[0]) directory.memberships.push({ user_id: user.id, project_id: directory.projects[0].id, role: 'admin' });
      }
      if (!process.env.EXCAVAGUARD_NEW_PASSWORD) {
        const credential = resolve(dirname(path), 'credentials', `${username}.txt`);
        mkdirSync(dirname(credential), { recursive: true, mode: 0o700 });
        writeFileSync(credential, `账号：${username}\n初始密码：${password}\n`, { mode: 0o600, flag: 'wx' });
        console.info(`初始凭据仅保存在本机文件：${credential}`);
      }
    } else {
      const user = directory.users.find(u => u.username === username);
      if (!user) throw new Error('未找到账号。');
      if (command === 'disable-user') user.disabled = true;
      else if (command === 'set-password') {
        if (!process.env.EXCAVAGUARD_NEW_PASSWORD) throw new Error('请通过EXCAVAGUARD_NEW_PASSWORD提供新密码。');
        user.password_hash = hashPassword(process.env.EXCAVAGUARD_NEW_PASSWORD);
      }
      else {
        const project = directory.projects.find(p => p.id === options.project && p.active);
        if (!project) throw new Error('未找到有效工程。');
        directory.memberships = directory.memberships.filter(m => !(m.user_id === user.id && m.project_id === project.id));
        if (command === 'grant') directory.memberships.push({ user_id: user.id, project_id: project.id, role: projectRoleSchema.parse(options.role) });
      }
    }
    writeFileSync(temporary, JSON.stringify(accessDirectorySchema.parse(directory), null, 2) + '\n', { mode: 0o600, flag: 'wx' });
    renameSync(temporary, path);
    console.info('账号/授权目录已更新；成员权限和停用状态在下一次请求立即生效。');
  }
} finally {
  rmSync(temporary, { force: true });
  rmSync(lock, { recursive: true, force: true });
}
