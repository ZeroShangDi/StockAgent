# GitHub Actions 自动部署到阿里云

这套配置的目标是：

- 你把代码推到远端 `feature-monitor` 分支
- GitHub Actions 自动通过 SSH 登录阿里云服务器
- 服务器进入项目目录，拉取最新代码
- 使用根目录 `docker compose --env-file .env.docker up -d --build` 重启服务

## 适用前提

当前仓库的服务器部署方式基于项目根目录的 `docker-compose.yml`，所以这套 CI/CD 默认也是围绕它设计的。

服务器需要满足：

- 已安装 `git`
- 已安装 `docker`
- 已安装 `docker compose` 插件或 `docker-compose`
- 服务器上已经克隆过本仓库
- 服务器项目目录里已经存在 `.env.docker`
- 服务器拉取远端仓库时已经具备权限
  - 公有仓库：直接 `git pull` 即可
  - 私有仓库：推荐在服务器上配置 SSH Deploy Key 或可读 PAT

## 仓库内新增内容

- Workflow：`/Users/shangjunhao/Project/StockAgent/.github/workflows/deploy-feature-monitor.yml`
- 服务器部署脚本：`/Users/shangjunhao/Project/StockAgent/tools/deploy/deploy_feature_monitor.sh`

## GitHub 需要配置的 Secrets

进入 GitHub 仓库：

`Settings -> Secrets and variables -> Actions`

新增以下 Secrets：

- `ALIYUN_HOST`
  - 例如：`123.123.123.123`
- `ALIYUN_PORT`
  - 一般为 `22`
- `ALIYUN_USER`
  - 例如：`root` 或专用部署用户
- `ALIYUN_SSH_KEY`
  - 用于登录服务器的私钥全文
- `ALIYUN_DEPLOY_PATH`
  - 服务器上的项目绝对路径
  - 例如：`/root/StockAgent`

## 建议的服务器准备步骤

第一次上线前，先在阿里云服务器手动完成一次基线部署：

```bash
cd /root
git clone <your-repo-url> StockAgent
cd StockAgent
git checkout feature-monitor
cp .env.docker.example .env.docker
# 然后手动编辑 .env.docker
docker compose --env-file .env.docker up -d --build
```

如果仓库是私有的，务必先让服务器上的 `git pull` 能直接成功。

## 这套部署具体做了什么

每次推送到 `feature-monitor` 后，GitHub Actions 会在服务器执行：

1. 校验服务器项目目录存在 `.env.docker`
2. 检查当前工作区是否干净
3. `git fetch origin feature-monitor`
4. 切到 `feature-monitor`
5. `git pull --ff-only origin feature-monitor`
6. `docker compose --env-file .env.docker up -d --build`
7. 输出当前容器状态

## 为什么没有用强制 reset

部署脚本故意没有使用 `git reset --hard`。

原因是：

- 服务器上如果有意外本地改动，强制覆盖风险更高
- 当前脚本会直接失败并暴露问题，避免“部署看似成功，实际把服务器手改配置冲掉”

如果你后面确定服务器目录永远只用于自动部署，也可以再升级成更激进的无状态部署脚本。

## 首次验证建议

推荐按下面顺序验证：

1. 在服务器手动执行一次脚本

```bash
cd /root/StockAgent
chmod +x tools/deploy/deploy_feature_monitor.sh
./tools/deploy/deploy_feature_monitor.sh
```

2. 确认脚本能成功：
   - `git pull` 正常
   - `docker compose up -d --build` 正常
   - 服务正常访问

3. 再推送一笔测试提交到 `feature-monitor`

4. 到 GitHub Actions 页面确认 workflow 成功

## 你接下来需要做什么

最少只需要做这几件事：

1. 在服务器上确认项目路径和 `git pull` 权限
2. 在 GitHub 仓库里补上 5 个 Secrets
3. 手动在服务器跑一次部署脚本
4. 推送测试提交到 `feature-monitor`

## 后续我还可以继续帮你的事

如果你愿意，我下一步还能继续帮你补这些增强项：

- 只重启受影响服务，而不是全量 `up -d --build`
- 部署前自动做前端 / 后端基础检查
- 部署失败时自动发钉钉或企业微信通知
- 增加生产分支和测试分支两套独立部署 workflow
