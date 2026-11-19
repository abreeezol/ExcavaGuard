# 阿里云轻量服务器部署

本镜像运行 Next.js + Python 确定性引擎 + openpyxl 三件套 + PDF文字层解析。
云端 RAG 使用 Pinecone；1GB服务器不在镜像中加载本地Torch/Chroma模型。
AI日报需要有效的LLM/Pinecone配置且服务器能够访问接口；模板日报不依赖它们。
部署前先确认当前Supabase项目已执行 `202611020001_collaboration.sql`。

2026-11-03 本机已构建并导出 `excavaguard:trial`（linux/amd64，tar约362MiB）。
镜像内使用合成输入和本地存储验证：健康接口、登录、CSV上传、Python计算、
模板日报审计、三份报告下载，以及独立管理员初始化和账号文件权限全部通过。
本次未验证服务器启动、真实Supabase迁移或云端AI调用。

## 1. Mac：构建并导出

在仓库根目录执行（Colima必须启动）：

```bash
sh deploy/build-image.sh trial
```

使用当前工作区源码，含未提交修改；排除全部环境文件、用户数据、账号目录和本地模型。
输出 `.artifacts/deploy/excavaguard-trial.tar`。构建完成后可停止Colima。

## 2. Mac：上传到服务器

阿里云防火墙允许SSH 22端口，使用服务器账号密码或SSH密钥。
Workbench网页的一键登录不会自动配置本机SSH。
若使用密码，请先在阿里云控制台设置服务器登录密码；不要发到聊天。

```bash
ssh admin@39.96.71.0 'mkdir -p ~/excavaguard/deploy'
scp .artifacts/deploy/excavaguard-trial.tar compose.yaml admin@39.96.71.0:~/excavaguard/
scp deploy/server.env.example admin@39.96.71.0:~/excavaguard/deploy/
```

## 3. 服务器：导入与配置

以下命令在服务器执行，先进入 `~/excavaguard`：

```bash
sudo docker load -i excavaguard-trial.tar
mkdir -p deploy/state
sudo chown -R 10001:10001 deploy/state
chmod 700 deploy/state
cp -n deploy/server.env.example deploy/server.env
chmod 600 deploy/server.env
nano deploy/server.env
```

若没有nano，用 `vi deploy/server.env`。填写Supabase URL、Secret和bucket。
首次工程UUID要与原数据的工程UUID一致，不能用工程名称替代。
云端AI配置从原环境配置填写；不要将`.env.local`或解密文件加入镜像。
账号目录使用下面初始化命令，配置文件中的共享密码和SESSION_SECRET可留空。
若采用旧共享密码方式，密码至少12字符，签名密钥至少32字符。

### 从旧服务器目录迁移配置

如果之前以 `root` 用户部署过，配置和账号目录可能仍在 `/root/excavaguard`。
更新到 `admin` 用户目录时，不要重新手填密钥，优先复制旧文件：

```bash
cd ~/excavaguard
sudo find /home/admin /root -path '*/excavaguard/deploy/server.env*' -type f -ls
sudo find /home/admin /root -path '*/excavaguard/deploy/state/access' -type d -print

mkdir -p deploy/state
sudo cp /root/excavaguard/deploy/server.env deploy/server.env
sudo chown admin:admin deploy/server.env
chmod 600 deploy/server.env

# 服务器没有 rsync 时使用 cp -a；不要用普通 cp -r 丢权限和隐藏文件。
sudo cp -a /root/excavaguard/deploy/state/. deploy/state/
sudo chown -R 10001:10001 deploy/state
```

复制完成后再执行 `docker compose up -d`。不要把 `server.env`、账号凭据或
`deploy/state/access/credentials/*.txt` 的内容粘贴到聊天或提交到仓库。

## 4. 服务器：初始化独立账号

先创建管理员；命令不打印密码，而在持久目录保存初始凭据。

```bash
sudo docker compose run --rm --no-deps app node tools/access/manage.mjs init --username admin --name 管理员
sudo docker compose run --rm --no-deps app node tools/access/manage.mjs add-user --username reviewer --name 复核工程师
sudo docker compose run --rm --no-deps app node tools/access/manage.mjs grant --username reviewer --project 11111111-1111-4111-8111-111111111111 --role reviewer
```

grant的工程UUID须与配置一致。上传者用 `add-user` 创建后赋予`engineer`角色。
若已有服务器账号目录，不重复init；它始终保留在 `deploy/state/access`。
在服务器私下读取 `deploy/state/access/credentials/<username>.txt` 并保存初始凭据，不上传聊天。

## 5. 服务器：启动与检查

```bash
sudo docker compose up -d
sudo docker compose ps
curl -fsS http://127.0.0.1:3000/api/health
```

首次只绑定服务器loopback，避免用公网明文HTTP传账号密码。
Mac终端开启SSH隧道：

```bash
ssh -N -L 3001:127.0.0.1:3000 admin@39.96.71.0
```

浏览器打开 `http://localhost:3001/workbench`。隧道期间保持这个SSH终端运行。
这是首次部署验证；多人公开使用再配置域名、HTTPS反向代理及相应备案/防火墙。
不需要启动Mac上的Colima。不要直接开放Docker远程API端口。

如果试运行阶段明确需要公网直连 `http://39.96.71.0:3000/workbench`，
可在服务器上的 `compose.yaml` 临时把端口改为公网绑定：

```bash
sed -i.bak 's/127\.0\.0\.1:3000:3000/3000:3000/' compose.yaml
sudo docker compose up -d
sudo docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'
```

公网绑定会暴露登录入口，正式多人使用前应改为 HTTPS 反向代理，不长期使用明文HTTP。

## 6. 更新与保留数据

在Mac构建新tag并上传，例如 `sh deploy/build-image.sh v2`。
服务器导入新tar，再执行：

```bash
sudo env EXCAVAGUARD_IMAGE_TAG=v2 docker compose up -d
```

后续compose命令也使用同一个tag（或在服务器compose同目录的`.env`仅保存该tag）。
回滚将tag改回旧版本。不要删除`deploy/state`；账号、项目规范SQLite和本地产物在该目录，
Supabase文件和运行记录保留在云端。更新前备份持久目录及环境配置，备份需私密保存。

更新后先保留上一个镜像tag，至少完成登录、项目打开、上传、报告生成和下载验收后再清理。
确认回滚不再需要时可查看并删除旧镜像：

```bash
sudo docker images 'excavaguard'
sudo docker image rm excavaguard:trial
```

1GB内存仅适合试运行，首次同时只生成一份报告；当前未实现跨用户全局任务排队。
若出现OOM、重启或持续Swap，应升级内存，不把Swap视为完整内存替代。
