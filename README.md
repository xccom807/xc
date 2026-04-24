# Kaspersky-519-WT-05（每日互助 / DailyHelper）

![Tests](https://github.com/YOUR_USERNAME/Kaspersky-519-WT-05-main/actions/workflows/test.yml/badge.svg)

一个基于 **Flask + 区块链** 的社区互助平台。用户可以发布求助、提交帮助提议、完成任务后通过链上支付结算并互评，所有关键操作均记录在内部审计链并可锚定至以太坊 Sepolia 测试网。

## 目录

- [系统架构](#系统架构)
- [核心功能 — 用户端](#核心功能--用户端)
- [核心功能 — 管理员端](#核心功能--管理员端)
- [底层系统](#底层系统)
- [数据模型](#数据模型)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [演示数据](#演示数据)
- [配置说明](#配置说明)
- [页面路由一览](#页面路由一览)
- [答辩演示流程](#答辩演示流程)
- [常见问题](#常见问题)
- [许可证](#许可证)

## 系统架构

### 技术栈

| 层面 | 技术 |
|---|---|
| **后端框架** | Flask 3.x（应用工厂 `create_app()` + 8 个 Blueprint 模块） |
| **数据库** | Flask-SQLAlchemy + SQLite（默认） |
| **用户认证** | Flask-Login + Flask-WTF（CSRF 全局保护） |
| **区块链** | 内部审计链（Block/Statement 哈希链） + web3.py（Sepolia 锚定） |
| **智能合约** | Solidity 0.8.24 + OpenZeppelin 5.x（ReputationSBT + TaskEscrow） |
| **合约工具** | Hardhat 编译部署 + Ethers.js v6 前端交互 |
| **钱包** | MetaMask 签名验证（challenge-response 协议） |
| **AI 助手** | Kimi / Moonshot API（多轮对话，最近 10 轮上下文） |
| **前端** | Jinja2 模板 + 原生 CSS/JS + Font Awesome 6.x |

### 架构总览

```
┌─────────────────────────────────────────────────────────┐
│                     浏览器 (用户/管理员)                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │
│  │ 仪表盘    │ │ 市场/详情 │ │ 私信/通知 │ │ 管理后台    │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └─────┬──────┘  │
└───────┼────────────┼────────────┼──────────────┼─────────┘
        │            │            │              │
        ▼            ▼            ▼              ▼
┌─────────────────────────────────────────────────────────┐
│         Flask 应用 (app.py + 8 个 Blueprint)              │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │ routes/                                            │  │
│  │  auth.py │ main.py │ features.py │ admin.py        │  │
│  │  profile.py │ messages.py │ blockchain.py │ api.py │  │
│  └────┬─────────────┬─────────────┬───────────┬──────┘  │
│       │             │             │            │          │
│       ▼             ▼             ▼            ▼          │
│  ┌────────────────────────────────────────────────────┐  │
│  │            SQLAlchemy ORM (models.py)               │  │
│  │  User | HelpRequest | HelpOffer | Review | Payment  │  │
│  │  Message | Notification | Flag | Block | Statement   │  │
│  └──────────────────────┬─────────────────────────────┘  │
│                         │                                 │
│  ┌──────────────────────▼─────────────────────────────┐  │
│  │          内部区块链 (blockchain_service.py)           │  │
│  │  Statement ──封块──> Block (prev_hash -> hash 链)    │  │
│  └──────────────────────┬─────────────────────────────┘  │
└─────────────────────────┼────────────────────────────────┘
                          │ 锚定 (submit_anchor_transaction)
                          ▼
              ┌───────────────────────────────────────────┐
              │            Ethereum Sepolia                │
              │  ┌──────────────┐  ┌───────────────────┐   │
              │  │ReputationSBT │  │   TaskEscrow      │   │
              │  │(灵魂绑定代币) │  │ (资金托管+DAO仲裁)│   │
              │  └──────────────┘  └───────────────────┘   │
              │       web3.py + Infura + Ethers.js          │
              └───────────────────────────────────────────┘
```

### 业务流程

```
用户A (求助者)                          用户B (帮助者)
    │                                       │
    │── 1. 发布求助 ───────────────────────>│
    │                                       │
    │<── 2. 提交帮助提议 ──────────────────│
    │                                       │
    │── 3a. 付费任务：接受提议 + Escrow 锁定 ETH ──>│
    │── 3b. 志愿任务：接受提议（旧流程）────>│
    │                                       │
    │<─────── 4. 私聊沟通 ────────────────>│
    │                                       │
    │── 5a. 确认完成 → Escrow 释放资金 ───>│  (付费)
    │── 5b. 标记任务完成 ─────────────────>│  (志愿)
    │                                       │
    │   ⚠️ 争议? → 发起仲裁 (Disputed) ────>│
    │         金牌用户投票 → 自动划转         │
    │                                       │
    │<─────── 6. 双向评价 ────────────────>│
    │         (对数衰减信誉分更新)            │
    │         (信誉达标 → Mint SBT)          │
    │                                       │
    ▼         全程上链审计 + 合约确权          ▼
```

## 核心功能 — 用户端

### 1. 账号系统
- **注册**：邮箱 + 用户名 + 密码，自动记录区块链审计
- **登录 / 登出**：邮箱 + 密码验证，黑名单用户禁止登录
- **忘记密码**：生成重置链接（token 有效期 1 小时）
- **重置密码**：通过 token 设置新密码

### 2. 个人资料
- **公开主页** (`/u/<username>`)：展示信誉分、等级、完成任务数、成功率、收到的评价
- **编辑资料** (`/settings/profile`)：修改全名、电话、地址、简介、技能、头像、经纬度
- **仪表盘** (`/dashboard`)：4 个统计卡片 + 快捷操作 + 最近动态 + 4 标签页切换

### 3. 互助任务全流程
- **发布求助**：标题、描述、分类、地点、时间、价格（或标记志愿）
- **帮助市场**：浏览所有开放求助，分类/地点/价格/日期/排序 多维筛选 + 分页
- **主动帮助**：浏览可帮助的请求，自动排除自己发布的和已提交过的
- **任务详情页**：完整生命周期（提交提议 → 接受 → 执行 → 完成 → 支付 → 评价）
- **取消求助**：求助者可取消自己的求助，自动通知帮助者
- **防重复提交**：同一帮助者不能对同一求助重复提交提议
- **我的帮助** (`/my-offers`)：按状态分组查看已提交的帮助记录

### 4. 支付系统（双轨模式）

**付费任务 — 智能合约托管 (Escrow)**：
1. 求助者接受提议时，唤起 MetaMask 向 TaskEscrow 合约存入约定 ETH（状态 → Locked）
2. 任务完成后，求助者点击“释放赏金”，合约自动打入帮助者钱包（状态 → Completed）
3. 若发生争议，任一方可发起仲裁（状态 → Disputed），由金牌用户投票裁决

**志愿任务 — 传统流程**：
1. 任务完成后，帮助者提交以太坊收款地址
2. 求助者在链上转账后，上传交易哈希作为支付凭证

### 5. 评价与信誉（对数衰减算法）
- 双方可对已完成任务进行 1-5 星评价 + 文字评论
- **信誉公式**：`delta = base_points × (1 / log₂(当前分 + 2)) × 评论字数加成`
  - 分越高，加分越少（对数衰减，防刷分）
  - 评论越详细，加成越大（鼓励认真评价）
  - 负面评价不衰减（始终全额扣分）
- **信誉等级**：新手(0-20) → 帮助者(20-50) → 可信赖(50-80) → 专家(80+)
- **信誉上链**：一键将信誉快照锚定至以太坊，生成可验证 JSON 证明

### 6. 私信系统
- 接受提议后，双方可进入私聊（入口在任务详情页）
- 消息收件箱按对话分组，显示最后一条消息和未读数
- 新消息自动触发站内通知

### 7. 通知系统
- 全局通知覆盖：帮助提议、接受/拒绝、任务完成、评价、支付、私信、管理员公告
- 导航栏实时显示未读通知和未读私信角标
- 支持单条标记已读 + 一键全部已读

### 8. 搜索与发现
- **全局搜索** (`/search`)：同时搜索求助（标题/描述/分类/地点）和用户（用户名/姓名/地点/技能），分页展示
- **排行榜** (`/leaderboard`)：信誉分排行 Top20、帮助次数排行、求助完成排行
- **志愿专区** (`/volunteer`)：专属筛选仅志愿类型的求助，支持分类/地点/日期筛选
- **附近的人** (`/nearby`)：基于 Haversine 公式计算距离，按半径/信誉/技能筛选附近用户

### 9. 举报系统
- 举报对象：用户、求助、评价
- 填写举报原因，提交后进入管理员审核队列

### 10. AI 智能助手
- **聊天页面** (`/chatbot`)：与 AI 助手"小美"对话
- **API 接口** (`/api/chatbot`)：调用 Kimi (Moonshot) API，保留最近 10 轮上下文

### 11. 钱包与 Web3
- **连接 MetaMask** (`/connect-wallet`)：绑定以太坊钱包到用户账号
- **钱包验证**：challenge-response 签名验证协议（防伪造）
- **我的钱包** (`/my-wallets`)：查看已绑定钱包列表
- **Web3 状态** (`/web3`)：查看 Sepolia 链连接状态、查询地址余额、手动上链

### 12. 灵魂绑定代币 (SBT)
- **Merkle Proof Mint**：信誉分≥20 且已绑定钱包的用户，可在个人主页免费铸造 SBT
- **三级等级**：🥉 铜牌（≥20）→ 🥈 银牌（≥50）→ 🥇 金牌（≥80）
- **自动升级**：信誉提升后可重新申领升级
- **链上查看**：个人主页自动显示链上 SBT 等级
- **不可转让**：合约禁止 transfer（灵魂绑定）

### 13. DAO 社区仲裁
- **仲裁大厅** (`/arbitration`)：信誉分≥80 的金牌用户导航栏自动解锁入口
- **争议列表**：展示所有 Disputed 状态的任务
- **链上投票**：唤起 MetaMask 调用 TaskEscrow.voteOnDispute（支持打款 / 支持退款）
- **跨合约校验**：合约自动验证投票者是否持有金牌 SBT
- **自动执行**：票数达到阈值（可配置，默认 1 票）自动划转资金

## 核心功能 — 管理员端

管理员登录后导航栏仅显示"管理后台 + 退出"，所有管理功能统一从 `/admin` 进入。管理员**不能**发布求助、提供帮助等用户级操作。

### 1. 管理后台首页 (`/admin`)
- 平台总览统计：用户数、总求助数、待匹配数、已完成数、举报数
- 近期注册用户列表
- 活动日志（最近 12 条 Statement 审计记录）
- 所有管理功能入口按钮

### 2. 用户管理 (`/admin/users`)
- 搜索用户（用户名/邮箱/姓名）
- 拉黑用户（支持填写原因）/ 取消拉黑
- 删除用户（不可撤销，需二次确认）
- 所有操作记录区块链审计日志

### 3. 求助管理 (`/admin/requests`)
- 查看所有求助列表（标题、发布者、分类、状态、价格、时间）
- 按关键词搜索 + 按状态筛选（待匹配/进行中/已完成/已取消）
- 分页浏览
- **管理员关闭任务**：一键关闭违规/争议求助，自动拒绝相关帮助提议，通知求助者和帮助者

### 4. 举报审核 (`/admin/moderation`)
- **举报处理**：查看待处理举报，通过（自动惩罚违规内容）或驳回

### 5. 支付记录 (`/admin/payments`)
- 查看所有支付记录（求助者→帮助者、金额、收款地址、交易哈希、状态）
- 按状态筛选（待支付/已支付）
- 交易哈希直接链接到 Etherscan 区块浏览器

### 6. 发布公告 (`/admin/broadcast`)
- 输入公告内容，一键群发给所有普通用户
- 以站内通知形式推送到每位用户的通知列表
- 记录区块链审计日志

### 7. 数据导出
- **导出用户** (`/admin/export/users`)：下载包含 ID、用户名、邮箱、全名、类型、信誉分、黑名单状态、注册时间的 CSV 文件
- **导出求助** (`/admin/export/requests`)：下载包含 ID、标题、发布者、分类、状态、价格、志愿标记、创建时间的 CSV 文件
- UTF-8 + BOM 编码，兼容 Excel 中文显示

### 8. 区块链与 Web3
- **区块链浏览器** (`/blockchain/blocks`)：查看内部审计链区块列表 → 区块详情 → Statement 详情
- **Web3 状态** (`/web3`)：查看 Sepolia 链连接状态、查询地址余额、手动提交锚定交易

### 9. SBT 信誉代币管理 (`/admin/sbt`)
- 查看所有合格用户（信誉≥20 且已绑定钱包）及其 SBT 等级
- 一键生成 Merkle Root 并上链至 ReputationSBT 合约
- 上链操作记录审计日志

## 底层系统

| 模块 | 说明 |
|---|---|
| **内部审计链** | 所有关键操作（注册/登录/发布/接受/支付/评价/管理操作等）记录为 `Statement`，每达到阈值（默认 10 条）自动封装为 `Block`（含 `prev_hash → hash` 哈希链） |
| **以太坊锚定** | 封块后可将 Block 哈希锚定至 Sepolia 测试网（可通过 `BLOCKCHAIN_ANCHOR_AUTO` 环境变量控制自动/手动） |
| **HTTP 请求审计** | 每个 HTTP 请求自动记录为 Statement（方法、路径、IP、UA、Referer） |
| **CSRF 保护** | Flask-WTF 全局 CSRF 令牌校验 |
| **角色隔离** | 管理员与普通用户导航栏和功能完全分离，管理员无法执行用户级操作 |
| **自定义错误页** | 404 / 500 自定义错误页面 |

## 数据模型

```
User ──────┬──> HelpRequest ──> HelpOffer ──> Review
           │         │              │
           │         v              │
           │      Payment <─────────┘
           │
           ├──> WalletLink (MetaMask 绑定)
           ├──> Message (私信)
           ├──> Notification (通知)
           └──> Statement ──> Block (内部区块链)

独立模型：Flag、PasswordResetToken
```

| 模型 | 说明 |
|---|---|
| `User` | 用户（含信誉分、经纬度、黑名单状态、用户类型） |
| `HelpRequest` | 求助请求（open → in_progress → completed / cancelled / disputed） |
| `HelpOffer` | 帮助提议（pending → accepted / rejected → completed） |
| `Review` | 双向评价（1-5 星 + 评论） |
| `Payment` | 支付记录（address_submitted → paid） |
| `Message` | 私信消息 |
| `Notification` | 站内通知（含管理员公告类型 `admin_broadcast`） |
| `WalletLink` | MetaMask 钱包绑定 |
| `Block` | 内部区块链区块 |
| `Statement` | 区块链审计日志条目 |
| `Flag` | 举报记录 |
| `PasswordResetToken` | 密码重置令牌 |

## 项目结构

```text
Kaspersky-519-WT-05-main/
├─ app.py                    # Flask 应用工厂 + Blueprint 注册 + 端点别名兼容
├─ config.py                 # 环境配置（SECRET_KEY、DB、Web3、日志等）
├─ models.py                 # 数据模型（12 个模型类）
├─ forms.py                  # WTForms 表单定义（15 个表单类）
├─ extensions.py             # db / login_manager / csrf 扩展实例
├─ blockchain_service.py     # 内部审计链写入与封块逻辑
├─ web3_service.py           # Web3 客户端初始化与链上锚定
├─ watch_blocks.py           # 区块观察工具（live mining）
├─ create_admin.py           # 创建默认管理员账号
├─ merkle_service.py         # Merkle Tree 生成 + Proof 查询 + 上链
├─ seed_demo_data.py         # 灌入演示数据（答辩用）
├─ routes/                   # ← 8 个 Blueprint 模块
│  ├─ auth.py               #   注册/登录/密码重置
│  ├─ main.py               #   首页/仪表盘/搜索/排行榜/志愿/附近
│  ├─ features.py           #   任务发布/市场/帮助/详情/评价/举报
│  ├─ admin.py              #   管理后台全功能
│  ├─ profile.py            #   个人主页/编辑/头像
│  ├─ messages.py           #   私信收件箱/聊天
│  ├─ blockchain.py         #   区块浏览器/信誉锚定
│  ├─ api.py                #   钱包/SBT/Escrow/AI 聊天
│  └─ helpers.py            #   共享工具函数
├─ tests/                    # ← 测试套件
│  └─ test_routes.py        #   100 个 pytest 集成测试
├─ contracts/                # Hardhat 智能合约项目
│  ├─ src/
│  │  ├─ ReputationSBT.sol     #   灵魂绑定信誉代币 (ERC-721 SBT)
│  │  └─ TaskEscrow.sol        #   任务资金托管 + DAO 仲裁
│  ├─ abi/                    #   合约 ABI（后端交互用）
│  ├─ scripts/deploy.js       #   部署脚本
│  ├─ hardhat.config.js       #   Hardhat 配置
│  └─ package.json            #   Node 依赖
├─ scripts/
│  └─ migrate_sqlite.py      # SQLite 增量迁移脚本
├─ templates/                # Jinja2 页面模板
│  ├─ base.html              #   全局基础模板（导航栏、角色隔离、Ethers.js CDN）
│  ├─ auth/                  #   注册 / 登录 / 密码重置
│  ├─ features/              #   求助 / 帮助 / 市场 / 详情 / 志愿 / 仲裁大厅
│  ├─ admin/                 #   管理后台（首页 / 用户 / 求助 / 审核 / 支付 / 公告 / SBT）
│  ├─ blockchain/            #   区块浏览器
│  ├─ messages/              #   私信收件箱 / 聊天
│  ├─ profile/               #   个人主页 / 编辑（含 SBT 状态）
│  ├─ wallet/                #   钱包绑定
│  └─ web3/                  #   Web3 状态
├─ static/
│  ├─ css/main.css           # 编译后的主样式表
│  ├─ js/main.js             # 客户端 JavaScript
│  └─ js/web3-integration.js # SBT/Escrow/DAO 前端交互 (Ethers.js)
├─ assets/scss/              # SCSS 源文件
├─ requirements.txt          # 完整依赖（锁定版本）
├─ run_app.bat               # 启动应用（含环境变量 + 合约地址）
├─ run_block1.bat             # 启动区块观察工具
└─ run_migration.bat          # 执行数据库迁移
```

## 快速开始

### 1) 环境要求

- Python 3.11 或 3.12（Windows 开发建议）
- pip 最新版本

### 2) 创建并激活虚拟环境（Windows）

```bat
python -m venv myenv
myenv\Scripts\activate
```

### 3) 安装依赖

```bat
pip install -r requirements.txt
```

### 4) 创建管理员账号

```bat
python create_admin.py
```

> 应用首次运行会自动执行 `db.create_all()` 创建所有表。

### 5) 灌入演示数据（推荐）

```bat
python seed_demo_data.py
```

该脚本会创建多个测试用户、求助任务、帮助提议、评价和私信，方便直接体验完整流程。详见 [演示数据](#演示数据) 章节。

### 6) 启动应用

**方式一**（推荐，使用批处理脚本，自动配置环境变量）：

```bat
run_app.bat
```

**方式二**（直接启动）：

```bat
python app.py
```

启动后访问：**http://127.0.0.1:5000**

## 演示数据

运行 `python seed_demo_data.py` 后，系统中将包含以下预置数据：

### 测试账号

| 角色 | 用户名 | 邮箱 | 密码 |
|---|---|---|---|
| 管理员 | `admin` | `admin@dailyhelper.com` | `admin123` |
| 求助者 | `alice` | `alice@test.com` | `test123` |
| 帮助者 | `bob` | `bob@test.com` | `test123` |
| 帮助者 | `charlie` | `charlie@test.com` | `test123` |
| 普通用户 | `diana` | `diana@test.com` | `test123` |
| 普通用户 | `eve` | `eve@test.com` | `test123` |
| 金牌专家 | `expert1` | `expert1@test.com` | `test123` |
| 金牌专家 | `expert2` | `expert2@test.com` | `test123` |
| 金牌专家 | `expert3` | `expert3@test.com` | `test123` |

### 预置内容

- **7 条求助**（覆盖不同分类、付费/志愿、不同状态，含 1 条 disputed 仲裁任务）
- **9 条帮助提议**（覆盖 pending/accepted/completed/rejected 状态）
- **4 条评价**（含不同星级和评论长度，信誉分已按对数公式计算）
- **3 个金牌专家用户**（信誉分 85，可测试 DAO 仲裁投票）
- **6 个钱包绑定**（alice/bob/charlie + 3 个专家，可测试 SBT Mint）
- **私信对话**（alice 与 bob 之间的任务沟通消息）
- **1 个已完成的支付记录**（含收款地址和交易哈希）
- **1 条举报**（待管理员处理）

## 配置说明

通过环境变量覆盖默认配置（`config.py`），也可在 `run_app.bat` 中修改：

| 变量名 | 默认值 | 说明 |
|---|---|---|
| `SECRET_KEY` | `change-this-in-production` | Flask 会话与安全密钥 |
| `DATABASE_URL` | `sqlite:///app.db` | SQLAlchemy 连接串 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `ETH_RPC_URL` | Sepolia Infura | Web3 RPC 地址 |
| `ETH_CHAIN_NAME` | `sepolia` | 链名称 |
| `ETH_CHAIN_ID` | `11155111` | 链 ID |
| `ETH_SIGNER_PRIVATE_KEY` | 已配置测试密钥 | 链上签名私钥（**勿泄露**） |
| `BLOCKCHAIN_ANCHOR_AUTO` | `false` | 是否自动上链锚定（`true` 可能导致请求变慢） |
| `BLOCK_SIZE` | `10` | 内部审计链封块阈值（多少条 Statement 封一个 Block） |
| `ETH_WAIT_FOR_RECEIPT` | `true` | 上链后是否等待交易确认 |
| `ETH_TX_TIMEOUT_SECONDS` | `180` | 等待交易确认的超时时间（秒） |
| `ETH_EXPLORER_TX_BASE_URL` | `https://sepolia.etherscan.io/tx` | 区块浏览器交易链接前缀 |
| `SBT_CONTRACT_ADDRESS` | 已部署 Sepolia 地址 | ReputationSBT 合约地址 |
| `ESCROW_CONTRACT_ADDRESS` | 已部署 Sepolia 地址 | TaskEscrow 合约地址 |
| `DAO_VOTE_THRESHOLD` | `1` | DAO 仲裁投票阈值（生产环境建议≥3） |
| `MOONSHOT_API_KEY` | - | Kimi AI 助手 API Key |

## 页面路由一览

### 公开页面（无需登录）

| 路由 | 说明 |
|---|---|
| `/` | 首页 |
| `/about` | 关于页面 |
| `/signup` | 注册 |
| `/login` | 登录 |
| `/marketplace` | 帮助市场（多维筛选 + 分页） |
| `/search` | 全局搜索（求助 + 用户） |
| `/leaderboard` | 排行榜（信誉/帮助/完成三维排行） |
| `/volunteer` | 志愿专区 |
| `/u/<username>` | 用户公开主页 |
| `/chatbot` | AI 智能助手 |
| `/web3` | Web3 连接状态 / 手动上链 |

### 用户页面（需登录）

| 路由 | 说明 |
|---|---|
| `/dashboard` | 仪表盘（4 标签页：概览 / 资料 / 我的求助 / 我的帮助） |
| `/request-help` | 发布求助 |
| `/offer-help` | 浏览可帮助的求助 |
| `/requests/<id>` | 求助详情（提议 / 接受 / 完成 / 支付 / 评价全流程） |
| `/requests/<id>/cancel` | 取消求助 |
| `/my-offers` | 我的帮助记录（按状态分组） |
| `/messages` | 私信收件箱 |
| `/messages/<user_id>` | 与指定用户的私聊对话 |
| `/notifications` | 通知列表 |
| `/notifications/<id>/read` | 标记通知已读 |
| `/notifications/read-all` | 一键全部已读 |
| `/settings/profile` | 编辑个人资料 |
| `/nearby` | 附近的人 |
| `/flag` | 举报（用户/求助/评价） |
| `/connect-wallet` | 绑定 MetaMask 钱包 |
| `/my-wallets` | 我的钱包列表 |
| `/blockchain/blocks` | 区块浏览器 |
| `/blockchain/reputation/anchor` | 信誉快照上链 |
| `/blockchain/reputation/proof/<username>` | 可验证信誉 JSON |

### 管理员页面（需管理员权限）

| 路由 | 说明 |
|---|---|
| `/admin` | 管理后台首页（总览统计 + 所有功能入口） |
| `/admin/users` | 用户管理（搜索 / 拉黑 / 删除） |
| `/admin/requests` | 求助管理（搜索 / 筛选 / 关闭任务） |
| `/admin/moderation` | 举报审核 |
| `/admin/payments` | 支付记录查看 |
| `/admin/broadcast` | 发布公告（群发站内通知） |
| `/admin/export/users` | 导出用户数据 CSV |
| `/admin/export/requests` | 导出求助数据 CSV |
| `/admin/sbt` | SBT 信誉代币管理（Merkle Root 上链） |

### API 接口

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/chatbot` | POST | AI 聊天接口 |
| `/api/submit-payment-address` | POST | 帮助者提交收款地址 |
| `/api/record-payment` | POST | 求助者上传支付凭证 |
| `/wallet/challenge` | POST | 钱包验证挑战 |
| `/wallet/verify` | POST | 钱包签名验证 |
| `/web3/balance` | GET | 查询以太坊地址余额 |
| `/api/sbt/proof` | GET | 获取当前用户的 Merkle Proof |
| `/api/sbt/status/<addr>` | GET | 查询钱包地址的 SBT 状态 |
| `/api/escrow/sync` | POST | Escrow 链上状态同步回调 |
| `/api/contracts/config` | GET | 获取合约地址和链配置 |
| `/arbitration` | GET | DAO 仲裁大厅（金牌用户） |

## 答辩演示流程

以下是建议的答辩演示顺序，覆盖所有核心功能（约 15 分钟）：

### 第一部分：用户与认证（2 分钟）

1. 打开首页，展示平台界面
2. 展示注册页面（字段校验）
3. 用 `alice / test123` 登录，展示仪表盘（4 标签页 + 快捷操作）
4. 查看个人资料页（信誉分 + 评价 + 信誉上链按钮）

### 第二部分：任务全流程（5 分钟）

5. 用 alice 发布一条新求助（展示分类、地点、价格等字段）
6. 退出，用 `bob / test123` 登录
7. 在帮助市场找到 alice 的求助，展示筛选功能，提交帮助提议
8. 退出，重新用 alice 登录
9. 在求助详情页接受 bob 的提议（展示其他提议自动拒绝）
10. 展示私聊入口，发一条消息给 bob
11. 标记任务完成

### 第三部分：支付与评价（3 分钟）

12. 用 bob 登录，在任务详情页提交收款地址
13. 用 alice 登录，上传交易哈希（展示支付状态流转）
14. 双方互评（展示对数衰减信誉公式效果：高分用户加分更少）

### 第四部分：区块链审计（2 分钟）

15. 访问 `/blockchain/blocks`，展示区块列表
16. 点进区块详情，查看 Statement 记录（各类操作审计日志）
17. 展示信誉快照上链功能
18. 访问 `/web3`，展示 Sepolia 连接状态，手动提交锚定交易

### 第五部分：管理后台（2 分钟）

19. 用 `admin / admin123` 登录，展示精简导航栏
20. 管理后台首页：展示统计数据 + 功能入口
21. 求助管理：查看所有求助，演示关闭任务
22. 用户管理：演示拉黑/解黑
23. 举报审核：处理举报
24. 支付记录：查看链上支付详情
25. 发布公告：群发站内通知
26. 数据导出：下载 CSV 文件

### 第六部分：Web3 智能合约（3 分钟）

27. 用 admin 登录，进入管理后台 → SBT 管理，展示合格用户列表
28. 点击"生成 Merkle Root 并上链"，展示链上交易成功
29. 用 alice 登录，访问个人主页，展示 SBT 状态区域，点击"申领 SBT"铸造
30. 用 expert1 登录，展示导航栏"仲裁大厅"入口，查看争议任务列表
31. 对争议任务投票"支持打款"，展示 MetaMask 交互

### 第七部分：其他亮点（1 分钟）

32. 搜索功能（同时搜索求助和用户）
33. 排行榜（三维排行）
34. AI 智能助手（与"小美"对话）
35. 志愿专区、附近的人（快速展示）

## 常见问题

### 登录/注册时报错：`Install 'email_validator' for email validation support`

```bat
pip install email-validator
```

该依赖已包含在 `requirements.txt` 中，确保已执行 `pip install -r requirements.txt`。

### 页面卡顿/加载慢

如果启用了自动上链（`BLOCKCHAIN_ANCHOR_AUTO=true`），每次封块会同步等待以太坊交易确认（最长 180 秒）。解决方案：

- 在 `run_app.bat` 中设置 `BLOCKCHAIN_ANCHOR_AUTO=false`（推荐，当前已默认关闭）
- 或增大 `BLOCK_SIZE`（如设为 100）减少封块频率
- 或设置 `ETH_WAIT_FOR_RECEIPT=false` 不等待交易确认

### 附近的人页面没有结果

- 确认当前用户已在个人资料中填写经纬度
- 确认筛选半径、最低信誉分与技能关键词是否过严

### 如何重置数据库

```bat
del instance\app.db
python create_admin.py
python seed_demo_data.py
python app.py
```

### AI 助手无回复

- 确认已配置 `MOONSHOT_API_KEY` 环境变量
- 确认 API Key 有效且有剩余额度

## 许可证

本项目采用仓库中的 `LICENSE` 文件约定。
