# CLAUDE.md — DailyHelper（每日互助）

> Flask + SQLite + Solidity 社区互助与链上托管平台，面向 AI 助手的快速上下文加载文档。

---

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11, Flask 3, SQLAlchemy 2, WTForms |
| 数据库 | SQLite（无迁移框架，依赖 `db.create_all()`） |
| 前端 | Jinja2 模板 + 原生 JS + Ethers.js v6 |
| 区块链 | web3.py, Sepolia 测试网 |
| 合约 | Solidity 0.8.x, Hardhat |
| 测试 | pytest (Python), Hardhat test (Solidity) |
| CI | GitHub Actions（Python + Solidity 双轨） |

---

## 项目结构

```
.
├── app.py                  # Flask 应用工厂、Blueprint 注册、端点别名、全局注入
├── config.py               # 配置类（SECRET_KEY, DATABASE_URL, 所有 ETH_*, SBT/ESCROW 地址）
├── models.py               # 全部 SQLAlchemy 模型（User, HelpRequest, HelpOffer, Payment, Review, WalletLink, Statement, Block, Appeal, Message, Notification, ChatbotMessage 等）
├── forms.py                # WTForms 表单（SignUp, Login, RequestHelp, OfferHelp, Review, Flag, Appeal 等）
├── extensions.py           # db, login_manager, csrf 三个扩展实例
├── blockchain_service.py   # 内部审计链：append_statement() + maybe_seal_block() + anchor_block()
├── web3_service.py         # 后端 Web3 交互：init_web3(), submit_anchor_transaction(), get_wallet_balance()
├── merkle_service.py       # SBT Merkle Proof 生成与验证
├── seed_demo_data.py       # 演示数据种子脚本
├── create_admin.py         # 创建管理员账号
│
├── routes/
│   ├── auth.py             # 注册/登录/登出/密码重置
│   ├── main.py             # 首页/仪表盘/排行榜/申诉/通知/搜索
│   ├── features.py         # 求助 CRUD/帮助申请/接受/取消/评价/举报/附近的人
│   ├── admin.py            # 管理后台：用户治理/内容审核/支付记录/广播/导出/SBT
│   ├── api.py              # 钱包绑定/Escrow 同步/SBT 状态/Web3 查询/Kimi AI
│   ├── blockchain.py       # 内部区块链浏览器
│   ├── profile.py          # 用户主页和资料编辑
│   ├── messages.py         # 私信系统
│   └── helpers.py          # 通用辅助装饰器（如 @login_required 变体）
│
├── contracts/
│   ├── src/ReputationSBT.sol   # 灵魂绑定信誉凭证（ERC-721, Merkle Proof Mint）
│   ├── src/TaskEscrow.sol      # 任务资金托管 + DAO 仲裁
│   ├── scripts/                # Hardhat 部署脚本
│   ├── test/ReputationSBT.test.js
│   └── test/TaskEscrow.test.js
│
├── templates/               # Jinja2 模板（按功能分子目录）
├── static/                  # CSS / JS / uploads
├── tests/test_routes.py     # Flask 路由集成测试（~500+ 行）
├── .github/workflows/test.yml  # CI：Python 集成测试 + Solidity 合约测试
└── .env.example             # 环境变量模板
```

---

## 核心架构约定

### Blueprint 注册

所有路由通过 Blueprint 注册（`routes/__init__.py` 统一导出），前缀规则：

```
auth_bp      → 无前缀（/login, /signup, /logout）
main_bp      → 无前缀（/, /dashboard, /leaderboard）
features_bp  → 无前缀（/request-help, /marketplace, /requests/<id>）
admin_bp     → /admin
api_bp       → 无前缀（/connect-wallet, /api/*, /arbitration）
blockchain_bp → /blockchain
profile_bp   → 无前缀（/u/<username>, /settings/profile）
messages_bp  → /messages
```

### 端点别名（向后兼容）

`app.py` 中的 `_ENDPOINT_ALIASES` 字典将旧端点名（如 `"login"`）映射到 Blueprint 端点（`"auth.login"`），通过 `url_build_error_handlers` 实现。**新增路由时不需要修改别名字典。**

### 数据库迁移风险

项目没有 Flask-Migrate / Alembic。修改模型后旧数据库不会自动新增字段。处理方式：
- 开发期：删除 `instance/app.db` 后重新 `python create_admin.py && python seed_demo_data.py`
- 或运行 `python scripts/migrate_sqlite.py`（部分场景）
- **修改模型前必须确认当前数据库状态**

---

## 核心业务状态机

### HelpRequest 状态流转

```
open → in_progress → completed
  ↓         ↓
cancelled  disputed → (仲裁后) completed / cancelled
```

### Escrow 链上状态 → 后端状态映射

| 链上动作 | 链上状态 | HelpRequest | Payment |
|---|---|---|---|
| createEscrow | Locked (1) | in_progress | — |
| releaseToHelper | Completed (2) | completed | paid |
| raiseDispute | Disputed (3) | disputed | — |
| 仲裁 PayHelper 胜 | Resolved (4) | completed | paid |
| 仲裁 RefundRequester 胜 | Resolved (4) | cancelled | refunded |

### 关键安全原则

1. **前端不可信**：`/api/escrow/sync` 在 `action=resolve` 时必须后端读链上票数决定结果，不信任前端 outcome
2. **付费 in_progress 任务不能普通取消**：钱已锁在合约里，必须走 releaseToHelper 或仲裁
3. **链上 Resolved ≠ 帮助者胜出**：必须读取 `votesForHelper` 和 `votesForRequester` 票数判断
4. **仲裁退款也扣手续费**：当前合约设计如此，不是 bug

---

## 常用命令

```bash
# 虚拟环境
myenv\Scripts\activate          # Windows
source myenv/bin/activate       # Linux/Mac

# 安装依赖
pip install -r requirements.txt

# 初始化数据
python create_admin.py
python seed_demo_data.py

# 启动应用
python app.py                    # http://127.0.0.1:5000
run_app.bat                      # Windows 一键启动

# 运行测试
python -m pytest tests/ -v
cd contracts && npx hardhat test
```

### 测试账号

| 用户 | 邮箱 | 密码 | 角色 |
|---|---|---|---|
| admin | admin@dailyhelper.com | admin123 | 管理员 |
| alice | alice@test.com | test123 | 普通用户 |
| bob | bob@test.com | test123 | 普通用户 |
| expert1-3 | expert1@test.com | test123 | 专家(SBT) |

---

## 模型字段注意事项

- `Payment.recipient_address` — 收款/退款地址，原字段名 helper_address 已在迁移中重命名
- `User.latitude/longitude` — Float 类型，用于附近的人功能
- `Statement.payload` — JSON 列，内部审计链的操作日志
- `HelpOffer.status` 包含 `completed` 状态但 ORM 默认只有 `pending/accepted/rejected`

---

## 已知问题与改进方向

1. **缺少数据库迁移框架** — 建议引入 Flask-Migrate/Alembic
2. ~~Payment 模型字段命名不准确~~ — 已修复：`helper_address` → `recipient_address`
3. **RPC 单点依赖** — 后端链上状态读取依赖 Sepolia RPC，无重试/降级机制
4. **无后台异步任务** — Escrow 同步和仲裁状态检查应转为后台轮询
5. **前端仍是传统 SSR** — Web3 状态交互复杂时 Jinja2 模板不够灵活，可考虑 Alpine.js 或组件化
6. **myenv 目录未加入 .gitignore** — 虚拟环境目录可能被意外提交（当前 .gitignore 中 myenv 未被忽略）
7. **`run_app.bat` 等 bat 脚本路径硬编码** — 依赖 Windows 路径和 myenv 目录结构
8. **Kimi API 超时无处理** — chatbot 调用无超时和重试逻辑
