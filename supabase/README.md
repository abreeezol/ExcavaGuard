# Supabase 接入操作

当前应用已显式切换到 Supabase Provider；本目录保存基础设施、检查和真实验收说明。
`var/` 中既有本地测试资产保留，不自动复制或删除。

## 0. 先轮换数据库密码

此前数据库密码曾出现在对话中，应视为已泄露。进入 Supabase Dashboard 的
Project Settings / Database，重置数据库密码。新密码不要发到对话、不要写入
`.env.local`，本应用运行时不需要它。

`SUPABASE_PROJECT_SECRET` 不是本项目支持的 API key 配置名。若其中放的是数据库
密码，应删除该整行；连接检查会主动拒绝这种误配置。

## 1. 在本机配置服务端 secret key

进入 Project Settings / API Keys / Publishable and secret API keys，找到并复制
`sb_secret_...` 开头的 Secret key。只在本机 `.env.local` 增加：

```dotenv
SUPABASE_SECRET_KEY=sb_secret_在控制台复制的值
SUPABASE_STORAGE_BUCKET=excavaguard-private
```

不要把 secret key 改成 `NEXT_PUBLIC_` 开头，也不要粘贴到聊天或提交 Git。
现有 `NEXT_PUBLIC_SUPABASE_URL` 和 `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
保留不动。

## 2. 执行一次数据库迁移

1. 打开 Supabase Dashboard / SQL Editor。
2. 新建 Query。
3. 把
   `supabase/migrations/202610140001_excavaguard_storage.sql`
   的完整内容粘贴进去。
4. 点击 Run。

该 SQL 可重复执行，创建五张元数据表、RLS 只读策略和私有
`excavaguard-private` bucket。它不创建公开对象访问策略。

## 3. 检查连接

```bash
npm run supabase:check
```

状态含义：

- `public_connected`：URL / publishable key 可达，但缺 secret 或迁移。
- `schema_ready`：服务端能读取目标表，bucket 存在且为 private。
- `infrastructure_verified`：执行了显式写探针，数据库和私有对象上传、下载、删除均通过。

迁移完成后运行一次写探针：

```bash
npm run supabase:verify
```

探针使用随机项目和随机对象，完成后立即删除。输出只包含布尔状态、表名和脱敏错误，
不打印任何 key。失败时保持本地 Provider，不设置
`EXCAVAGUARD_STORAGE_PROVIDER=supabase`。

## 4. 应用 Provider 验收

Supabase Provider 已实现并覆盖：

- 监测文件和用户规范对象与 SHA-256 元数据一致；
- Python 引擎从随机临时目录读取并在调用后清理；
- 运行 revision 并发写入恰好一个成功，竞争者返回 `RUN_CONFLICT`；
- 审计后三件套上传私有 bucket，下载与人工接受重新校验哈希；
- 对象与元数据部分失败时补偿清理或显式失败；
- live 测试完成后清理文件、运行、报告元数据和对象。

真实验收命令：

```bash
npm run supabase:test
```

当前 `.env.local` 已设置 `EXCAVAGUARD_STORAGE_PROVIDER=supabase`。本地历史数据
仍只通过后续显式迁移命令复制，不自动删除。
