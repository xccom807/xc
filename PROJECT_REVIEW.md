# DailyHelper（每日互助）项目评审报告

> 生成时间：2025-04-24（更新） | 评审工具：Cascade AI
> 本文档可直接提供给 AI 助手，帮助其快速理解项目全貌。

---

## 一、项目总览

| 项目 | 内容 |
|---|---|
| **名称** | Kaspersky-519-WT-05 / DailyHelper（每日互助） |
| **定位** | 基于 Flask + 区块链的社区互助平台 |
| **核心业务** | 发布求助 → 帮助提议 → 接受 → 执行 → 支付 → 评价，全程链上审计 |
| **技术栈** | Flask 3.x / SQLAlchemy + SQLite / web3.py 7.x / Solidity 0.8.24 + OpenZeppelin 5.x / Hardhat / Ethers.js v6 / Jinja2 + 原生 CSS/JS |
| **代码规模** | Python ~4200 行（含测试） / Solidity ~570 行 / JS ~830 行（含合约测试） / HTML 模板 47 个 / SCSS 18 个 |
| **合约部署** | Sepolia 测试网（ReputationSBT + TaskEscrow 已部署） |

---

## 二、综合评分

| 维度 | 得分 (10分制) | 说明 |
|---|---|---|
| **功能完整性** | 9.0 | 覆盖互助全生命周期 + 支付 + 评价 + 仲裁 + SBT + AI，功能非常丰富 |
| **架构设计** | 8.5 | 应用工厂模式 + 8 个 Blueprint 分层（auth/main/features/admin/profile/messages/blockchain/api），向后兼容端点别名 |
| **代码质量** | 7.0 | 命名清晰、注释到位，但有少量代码问题（见下方详细列表） |
| **区块链集成** | 9.0 | 内部审计链 + Sepolia 锚定 + SBT Merkle Mint + Escrow 资金托管 + DAO 仲裁，设计完整 |
| **智能合约** | 9.0 | Solidity 代码规范，使用 OpenZeppelin 库，SBT 灵魂绑定 + Escrow 重入保护 + 手续费机制 |
| **安全性** | 7.5 | CSRF 保护到位，敏感配置已迁移至 `.env` 环境变量（私钥/API Key/Infura），提供 `.env.example` 模板 |
| **前端/UX** | 7.0 | 功能页面齐全，SCSS 主题化，但非 SPA，交互体验偏传统 |
| **文档** | 9.5 | README 极其详尽（615行），含架构图、流程图、路由表、演示流程、FAQ |
| **测试** | 9.0 | 100 个 pytest 集成测试 + 63 个 Hardhat 合约测试（覆盖 SBT Mint/升级/灵魂绑定/Escrow 全生命周期/DAO 仲裁/手续费） |
| **可维护性** | 8.0 | Blueprint 分层清晰，共享 helpers.py 模块，路由文件职责单一 |

### **总分：8.9 / 10**

> 作为一个课程/答辩项目，功能覆盖面和文档质量**远超平均水平**。已完成 Blueprint 架构重构、163 个自动化测试（100 pytest + 63 Hardhat）、安全加固（环境变量隔离）。剩余优化项为前端体验和性能。

---

## 三、项目架构

```
浏览器 ──HTTP──> Flask app.py (应用工厂 + Blueprint 注册)
                    │
                    ├── routes/          ← 8 个 Blueprint 模块
                    │   ├── auth.py       (注册/登录/密码)
                    │   ├── main.py       (首页/仪表盘/搜索/排行榜)
                    │   ├── features.py   (任务/市场/帮助/评价/志愿/附近)
                    │   ├── admin.py      (管理后台全功能)
                    │   ├── profile.py    (个人主页/编辑/头像)
                    │   ├── messages.py   (私信收件箱/聊天)
                    │   ├── blockchain.py (区块浏览器/信誉锚定)
                    │   ├── api.py        (钱包/SBT/Escrow/AI聊天)
                    │   └── helpers.py    (共享工具函数)
                    ├── extensions.py (db / login_manager / csrf)
                    ├── models.py (12个数据模型)
                    ├── forms.py (15个WTForms表单)
                    ├── blockchain_service.py (内部审计链: Statement → Block)
                    ├── web3_service.py (以太坊交互: 签名、上链)
                    ├── merkle_service.py (Merkle Tree + SBT Proof)
                    ├── config.py (环境配置)
                    └── tests/test_routes.py (100个集成测试)

智能合约 (Sepolia):
    ├── ReputationSBT.sol (ERC-721 灵魂绑定代币, Merkle Proof Mint)
    └── TaskEscrow.sol (资金托管 + DAO仲裁, 跨合约验证SBT)

前端:
    ├── templates/ (47个Jinja2模板)
    ├── static/js/web3-integration.js (Ethers.js v6 合约交互)
    └── assets/scss/ (18个SCSS源文件)
```

---

## 四、核心功能模块

### 4.1 用户系统
- 注册/登录/登出（Flask-Login + 密码哈希）
- 忘记密码 → 重置令牌（1小时有效）
- 个人资料（头像上传、技能、经纬度）
- 用户公开主页（`/u/<username>`）
- 角色隔离：admin / user，导航栏和功能完全分离

### 4.2 互助任务全流程
- 发布求助（分类/地点/价格/志愿/技能/时间）
- 帮助市场（多维筛选 + 分页）
- 提交帮助提议 → 求助者接受/拒绝
- 私聊沟通（消息收件箱 + 对话分组）
- 标记完成 → 双方互评
- 取消/编辑求助

### 4.3 支付系统（双轨模式）
- **付费任务 — Escrow 合约托管**：接受提议时锁定ETH → 完成后释放 → 争议可仲裁
- **志愿任务 — 传统流程**：帮助者提交收款地址 → 求助者上传 tx_hash

### 4.4 信誉系统（对数衰减算法）
- 公式：`delta = base_points × (1 / log₂(当前分 + 2)) × 评论字数加成`
- 四级等级：新手(0-20) → 帮助者(20-50) → 可信赖(50-80) → 专家(80+)
- 信誉快照可锚定至以太坊

### 4.5 区块链审计链
- 所有关键操作记录为 `Statement`（kind + payload + user_id）
- 每 10 条自动封装为 `Block`（SHA-256 哈希链，prev_hash → hash）
- 可选自动锚定至 Sepolia（submit_anchor_transaction）
- 区块浏览器（`/blockchain/blocks`）

### 4.6 智能合约
- **ReputationSBT** (221行)：ERC-721 灵魂绑定代币，Merkle Proof Mint，三级等级
- **TaskEscrow** (347行)：资金托管、释放、争议仲裁，跨合约验证 SBT 等级，手续费机制

### 4.7 DAO 仲裁
- 金牌用户（信誉≥80）可进入仲裁大厅
- 链上投票（voteOnDispute），跨合约校验 Gold SBT
- 票数达阈值自动执行资金划转

### 4.8 其他功能
- AI 聊天助手（Kimi/Moonshot API，10轮上下文）
- 全局搜索（求助 + 用户）
- 排行榜（信誉/帮助/完成三维）
- 志愿专区、附近的人（Haversine 公式）
- 举报系统、通知系统
- 管理后台（用户管理/求助管理/审核/支付/公告/导出CSV/SBT管理）

---

## 五、数据模型（12个）

| 模型 | 关键字段 |
|---|---|
| `User` | username, email, password_hash, reputation_score, user_type, is_blacklisted, lat/lng, bio, skills, avatar |
| `HelpRequest` | title, description, category, location, price, is_volunteer, status(open/in_progress/completed/cancelled/disputed) |
| `HelpOffer` | request_id, helper_id, message, status(pending/accepted/rejected/completed) |
| `Review` | request_id, reviewer_id, reviewee_id, rating(1-5), comment |
| `Payment` | request_id, helper_address, amount, tx_hash, status(address_submitted/paid) |
| `Message` | sender_id, receiver_id, content, is_read |
| `Notification` | user_id, kind, message, link, is_read |
| `WalletLink` | user_id, address, challenge_nonce, verified_at |
| `Block` | index, prev_hash, hash |
| `Statement` | kind, payload(JSON), user_id, block_id |
| `Flag` | content_type, content_id, reason, status |
| `PasswordResetToken` | user_id, token, used |

---

## 六、技术亮点

1. **内部审计链 + Sepolia 双层区块链架构**：SQLite 存储的轻量哈希链 + 可选以太坊锚定，兼顾性能和可验证性
2. **Merkle Tree SBT**：后端构建 Merkle Tree → 管理员上链 Root → 用户凭 Proof 免费 Mint，完全匹配 Solidity 编码
3. **TaskEscrow + DAO 仲裁**：Escrow 托管 + 跨合约 SBT 等级验证 + 自动执行，形成闭环
4. **对数衰减信誉算法**：防刷分 + 鼓励详细评价，设计合理
5. **Challenge-Response 钱包验证**：MetaMask 签名 → 后端恢复地址，标准 Web3 身份验证流程
6. **全面的区块链审计日志**：几乎所有业务操作（注册/登录/发布/接受/支付/评价/管理操作/HTTP请求）都记录上链

---

## 七、发现的问题与改进建议

### 🔴 严重问题

| # | 问题 | 位置 | 建议 |
|---|---|---|---|
| 1 | ~~**私钥硬编码**~~ | `config.py` | ✅ **已修复**：默认值为空字符串，通过 `.env` 环境变量注入 |
| 2 | ~~**API Key 硬编码**~~ | `config.py` | ✅ **已修复**：同上 |
| 3 | ~~**Infura Key 暴露**~~ | `hardhat.config.js` | ✅ **已修复**：使用 `dotenv` 从 `.env` 读取，已移除硬编码 URL |

### 🟡 中等问题

| # | 问题 | 建议 |
|---|---|---|
| 4 | ~~全部路由在单文件 app.py~~ | ✅ **已修复**：拆分为 8 个 Blueprint 模块 |
| 5 | ~~无任何测试文件~~ | ✅ **已修复**：100 个 pytest 集成测试 + 63 个 Hardhat 合约测试 |
| 6 | requirements.txt 缺少 flask-login、flask-wtf、email-validator | 补全所有直接依赖 |
| 7 | 模型懒导入（路由函数内 `from models import ...`） | 改为文件顶部统一导入，仅在确实有循环依赖时才懒导入 |

### 🟢 轻微/优化建议

| # | 建议 |
|---|---|
| 11 | 添加 rate limiting（如 Flask-Limiter）防止 API 滥用 |
| 12 | 信誉分上限硬编码为 100.0，可改为配置项 |
| 13 | 搜索功能可加入全文索引（FTS5）提升性能 |
| 14 | 前端可引入 Alpine.js 或 HTMX 提升交互体验 |
| 15 | 考虑添加 WebSocket 实现私信实时推送 |

---

## 八、关键文件索引

| 文件 | 行数 | 职责 |
|---|---|---|
| `app.py` | ~170 | Flask 应用工厂 + Blueprint 注册 + 向后兼容端点别名 |
| `routes/auth.py` | ~180 | 认证路由（注册/登录/密码重置） |
| `routes/main.py` | ~260 | 主路由（首页/仪表盘/搜索/排行榜/志愿/附近） |
| `routes/features.py` | ~750 | 任务路由（发布/市场/帮助/详情/评价/举报） |
| `routes/admin.py` | ~310 | 管理后台路由 |
| `routes/profile.py` | ~120 | 个人资料路由 |
| `routes/messages.py` | ~75 | 私信路由 |
| `routes/blockchain.py` | ~120 | 区块链浏览器/信誉锚定路由 |
| `routes/api.py` | ~490 | API 路由（钱包/SBT/Escrow/AI 聊天） |
| `models.py` | 258 | 12 个 SQLAlchemy 数据模型 |
| `forms.py` | 179 | 15 个 WTForms 表单类 |
| `config.py` | 45 | 环境配置（DB/Web3/合约/AI） |
| `extensions.py` | 10 | db / login_manager / csrf 扩展实例 |
| `blockchain_service.py` | 121 | 内部审计链：Statement 写入 + Block 封块 + 自动锚定 |
| `web3_service.py` | 147 | Web3 客户端初始化 + 链上锚定交易（带重试） |
| `merkle_service.py` | 297 | Merkle Tree 构建 + Proof 生成 + Root 上链 |
| `contracts/src/ReputationSBT.sol` | 221 | ERC-721 灵魂绑定信誉代币 |
| `contracts/src/TaskEscrow.sol` | 347 | 任务资金托管 + DAO 仲裁合约 |
| `contracts/test/ReputationSBT.test.js` | ~250 | SBT 合约测试（24 个用例） |
| `contracts/test/TaskEscrow.test.js` | ~290 | Escrow 合约测试（39 个用例） |
| `static/js/web3-integration.js` | 325 | Ethers.js 前端合约交互（SBT Mint/Escrow/仲裁） |
| `seed_demo_data.py` | - | 演示数据灌入脚本 |
| `create_admin.py` | - | 创建管理员账号 |
| `tests/test_routes.py` | ~530 | 100 个 pytest 集成测试 |

---

## 九、环境与运行

```bash
# 安装依赖
python -m venv myenv && myenv\Scripts\activate
pip install -r requirements.txt

# 初始化
python create_admin.py        # 创建管理员 (admin / admin123)
python seed_demo_data.py      # 灌入演示数据

# 启动
run_app.bat                   # 或 python app.py
# 访问 http://127.0.0.1:5000

# 合约编译（Node.js 环境）
cd contracts && npm install && npx hardhat compile
```

### 测试账号

| 角色 | 用户名 | 密码 |
|---|---|---|
| 管理员 | admin | admin123 |
| 求助者 | alice | test123 |
| 帮助者 | bob | test123 |
| 帮助者 | charlie | test123 |
| 金牌专家 | expert1/2/3 | test123 |

---

## 十、给 AI 助手的上下文摘要

> 如果你是一个 AI 助手，以下是你需要知道的关键信息：

1. **这是一个 Flask Blueprint 应用**，路由分布在 `routes/` 目录下 8 个 Blueprint 模块中，`app.py` 仅负责工厂注册（~170 行），向后兼容的端点别名通过 `url_build_error_handlers` 实现。
2. **数据库是 SQLite**（`instance/app.db`），通过 `db.create_all()` 自动建表，无迁移框架（Alembic）。
3. **区块链有两层**：
   - 内部链：`Statement` → `Block`（SHA-256 哈希链），存在 SQLite
   - 外部链：Sepolia 测试网，通过 `web3_service.py` 发送交易
4. **智能合约已部署**在 Sepolia，地址在 `config.py` 中配置。合约 ABI 在 `contracts/abi/` 目录。
5. **前端是服务端渲染**（Jinja2 模板），无前端构建流程。Web3 交互通过 CDN 引入的 Ethers.js v6。
6. **163 个自动化测试**：100 个 pytest 集成测试（`tests/test_routes.py`）+ 63 个 Hardhat 合约测试（`contracts/test/`）。运行 `python -m pytest tests/ -v` 和 `cd contracts && npx hardhat test` 分别验证。
6b. **敏感配置**已从代码中移除，统一通过 `.env` 文件注入（见 `.env.example`）。
7. **修改数据模型后**，需要删除 `instance/app.db` 重建（无迁移），或手动用 `scripts/migrate_sqlite.py`。
8. **CSRF 保护**已全局启用，API 端点通过 `@csrf.exempt` 豁免。
9. **合约交互关键流程**：后端 `merkle_service.py` 构建 Merkle Tree → 管理员上链 Root → 前端 `web3-integration.js` 通过 MetaMask 调用合约。
10. **项目语言为中文**，所有 flash 消息、表单标签、模板文本均为中文。
