# Kaspersky-519-WT-05（每日互助 / DailyHelper）

一个基于 **Flask + 区块链** 的社区互助平台。用户可以发布求助、提交帮助提议、完成任务后通过链上支付结算并互评，所有关键操作均记录在内部审计链并可锚定至以太坊 Sepolia 测试网。

## 目录

- [系统架构](#系统架构)
- [核心功能](#核心功能)
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
| **后端框架** | Flask 3.x（应用工厂 `create_app()`） |
| **数据库** | Flask-SQLAlchemy + SQLite（默认） |
| **用户认证** | Flask-Login + Flask-WTF（CSRF） |
| **区块链** | 内部审计链（Block/Statement 哈希链） + web3.py（Sepolia 锚定） |
| **钱包** | MetaMask 签名验证（challenge-response） |
| **前端** | Jinja2 模板 + 原生 CSS/JS + Font Awesome |

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
│                    Flask 应用 (app.py)                    │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │
│  │ 用户认证  │ │ 任务管理  │ │ 支付流程  │ │ 信誉系统    │  │
│  │ 注册/登录 │ │ CRUD     │ │ 地址→转账 │ │ 对数衰减    │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └─────┬──────┘  │
│       │            │            │              │          │
│       ▼            ▼            ▼              ▼          │
│  ┌────────────────────────────────────────────────────┐  │
│  │            SQLAlchemy ORM (models.py)               │  │
│  │  User | HelpRequest | HelpOffer | Review | Payment  │  │
│  │  Message | Notification | NGO | Flag | Block | ...   │  │
│  └──────────────────────┬─────────────────────────────┘  │
│                         │                                 │
│  ┌──────────────────────▼─────────────────────────────┐  │
│  │          内部区块链 (blockchain_service.py)           │  │
│  │  Statement ──封块──> Block (prev_hash -> hash 链)    │  │
│  └──────────────────────┬─────────────────────────────┘  │
└─────────────────────────┼────────────────────────────────┘
                          │ 锚定 (submit_anchor_transaction)
                          ▼
              ┌───────────────────────┐
              │  Ethereum Sepolia     │
              │  (web3.py + Infura)   │
              └───────────────────────┘
```

### 业务流程

```
用户A (求助者)                          用户B (帮助者)
    │                                       │
    │── 1. 发布求助 ───────────────────────>│
    │                                       │
    │<── 2. 提交帮助提议 ──────────────────│
    │                                       │
    │── 3. 接受提议 (自动拒绝其他) ───────>│
    │                                       │
    │<─────── 4. 私聊沟通 ────────────────>│
    │                                       │
    │── 5. 标记任务完成 ──────────────────>│
    │                                       │
    │<── 6. 帮助者提交收款地址 ────────────│
    │                                       │
    │── 7. 求助者链上转账 + 上传 tx_hash ─>│
    │                                       │
    │<─────── 8. 双向评价 ────────────────>│
    │         (对数衰减信誉分更新)            │
    │                                       │
    ▼         全程上链审计                    ▼
```

## 核心功能

### 1. 用户系统
- 注册 / 登录 / 登出 / 忘记密码 / 重置密码 / 修改密码
- 个人资料编辑（技能、简介、头像、经纬度）
- 公开主页（信誉分、评价、完成率、信誉等级）

### 2. 互助任务全流程
- **发布求助**：分类、描述、地点、时段、预算、志愿标签
- **帮助市场**：分类/地点/价格区间/日期/排序 多维筛选 + 分页
- **任务详情页**：提交提议 -> 接受 -> 执行 -> 完成 -> 支付 -> 评价
- **防重复提交**：同一帮助者不能对同一求助重复提交提议
- **编辑/取消**：求助者可编辑开放状态的求助，或取消求助

### 3. 支付系统（两步链上结算）
1. 任务完成后，**帮助者**提交以太坊收款地址（含地址格式校验）
2. **求助者**在链上转账后，上传交易哈希（tx_hash）作为支付凭证
3. 系统记录支付状态，双方均可查看 Etherscan 链接

### 4. 评价与信誉（对数衰减算法）
- 双方可对已完成任务进行 1-5 星评价 + 文字评论
- **信誉公式**：`delta = base_points * (1 / log2(当前分 + 2)) * 评论字数加成`
  - 分越高，加分越少（对数衰减）
  - 评论越详细，加成越大（鼓励认真评价）
  - 负面评价不衰减（始终全额扣分）
- 信誉等级：新手(0-20) -> 帮助者(20-50) -> 可信赖(50-80) -> 专家(80+)
- 信誉快照可一键上链锚定，生成可验证 JSON 证明

### 5. 私信系统
- 接受提议后，双方可进入私聊（入口在任务详情页）
- 消息收件箱 + 实时未读角标
- 新消息自动通知

### 6. 通知系统
- 全局通知（提议、接受、拒绝、完成、评价、支付、私信等事件）
- 导航栏未读角标提醒

### 7. 区块链审计
- **内部链**：所有关键操作（注册/登录/发布/接受/支付/评价等）记录为 Statement
- **自动封块**：达到阈值后封装为 Block（prev_hash -> hash 哈希链）
- **链上锚定**：区块哈希可锚定至 Ethereum Sepolia 测试网
- **区块浏览器**：`/blockchain/blocks` -> 区块详情 -> Statement 详情
- **钱包绑定**：MetaMask 签名验证（challenge-response 协议）

### 8. 其他功能
- **全局搜索**：同时搜索求助和用户
- **排行榜**：信誉分 / 帮助次数 / 求助完成 三维排行
- **志愿专区**：专属志愿服务筛选页面
- **附近的人**：Haversine 公式 + 距离/信誉/技能筛选
- **公益组织**：NGO 列表、详情、提交审核
- **举报系统**：举报求助/用户/评价 + 管理员审核处置
- **管理后台**：仪表盘 / 用户管理(拉黑/删除) / 审核中心(Flag+NGO)
- **仪表盘**：4 标签页（概览+快捷操作 / 资料+信誉+评价 / 我的求助 / 我的帮助）

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

独立模型：NGO、Flag、PasswordResetToken
```

| 模型 | 说明 |
|---|---|
| `User` | 用户（含信誉分、经纬度、黑名单状态） |
| `HelpRequest` | 求助请求（open -> in_progress -> completed/cancelled） |
| `HelpOffer` | 帮助提议（pending -> accepted/rejected -> completed） |
| `Review` | 双向评价（1-5 星 + 评论） |
| `Payment` | 支付记录（address_submitted -> paid） |
| `Message` | 私信消息 |
| `Notification` | 站内通知 |
| `WalletLink` | MetaMask 钱包绑定 |
| `Block` | 内部区块链区块 |
| `Statement` | 区块链审计日志条目 |
| `NGO` | 公益组织 |
| `Flag` | 举报记录 |

## 项目结构

```text
Kaspersky-519-WT-05-main/
├─ app.py                    # Flask 应用入口与全部路由（约 2600 行）
├─ config.py                 # 环境配置（SECRET_KEY、DB、Web3、日志等）
├─ models.py                 # 数据模型（12 个模型类）
├─ forms.py                  # WTForms 表单定义（11 个表单类）
├─ extensions.py             # db / login_manager / csrf 扩展实例
├─ blockchain_service.py     # 内部审计链写入与封块逻辑
├─ web3_service.py           # Web3 客户端初始化与链上锚定
├─ watch_blocks.py           # 区块观察工具
├─ init_db.py                # 初始化数据库
├─ create_admin.py           # 创建默认管理员
├─ seed_demo_data.py         # 灌入演示数据（答辩用）
├─ scripts/
│  └─ migrate_sqlite.py      # SQLite 增量迁移脚本
├─ templates/                # 42 个 Jinja2 页面模板
│  ├─ auth/                  #   注册/登录/密码重置
│  ├─ features/              #   求助/帮助/市场/详情/NGO/志愿/附近
│  ├─ admin/                 #   管理后台
│  ├─ blockchain/            #   区块浏览器
│  ├─ messages/              #   私信收件箱/聊天
│  ├─ profile/               #   个人主页/编辑
│  ├─ wallet/                #   钱包绑定
│  └─ web3/                  #   Web3 状态
├─ static/                   # CSS / JS 静态资源
├─ requirements.txt          # 完整依赖（锁定版本）
└─ requirements.app.txt      # 应用关键依赖
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
pip install -r requirements.app.txt
```

### 4) 初始化数据库并创建管理员

```bat
python init_db.py
python create_admin.py
```

> 应用首次运行也会自动 `create_all()`，`init_db.py` 为可选步骤。

### 5) 灌入演示数据（推荐）

```bat
python seed_demo_data.py
```

该脚本会创建多个测试用户、求助任务、帮助提议、评价和私信，方便直接体验完整流程。详见 [演示数据](#演示数据) 章节。

### 6) 启动应用

```bat
python app.py
```

启动后访问：`http://127.0.0.1:5000`

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

### 预置内容

- **6 条求助**（覆盖不同分类、付费/志愿、不同状态）
- **8 条帮助提议**（覆盖 pending/accepted/completed/rejected 状态）
- **4 条评价**（含不同星级和评论长度，信誉分已按对数公式计算）
- **私信对话**（alice 与 bob 之间的任务沟通消息）
- **1 个已完成的支付记录**（含收款地址和交易哈希）
- **2 个 NGO**（1 个已认证、1 个待审核）
- **1 条举报**（待管理员处理）

## 配置说明

通过环境变量覆盖默认配置（`config.py`）：

| 变量名 | 默认值 | 说明 |
|---|---|---|
| `SECRET_KEY` | `change-this-in-production` | Flask 会话与安全密钥 |
| `DATABASE_URL` | `sqlite:///app.db` | SQLAlchemy 连接串 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `ETH_RPC_URL` | Sepolia Infura | Web3 RPC 地址 |
| `ETH_CHAIN_NAME` | `sepolia` | 链名称 |
| `ETH_SIGNER_PRIVATE_KEY` | 已配置测试密钥 | 链上签名私钥 |
| `BLOCK_SIZE` | `10` | 内部审计链封块阈值 |

## 页面路由一览

| 路由 | 说明 | 权限 |
|---|---|---|
| `/signup` | 注册 | 公开 |
| `/login` | 登录 | 公开 |
| `/dashboard` | 仪表盘（4 标签页） | 登录 |
| `/request-help` | 发布求助 | 登录 |
| `/marketplace` | 帮助市场（筛选+分页） | 公开 |
| `/requests/<id>` | 求助详情（提议/接受/完成/支付/评价） | 登录 |
| `/offer-help` | 浏览可帮助的求助 | 登录 |
| `/my-offers` | 我的帮助记录 | 登录 |
| `/messages` | 私信收件箱 | 登录 |
| `/messages/<user_id>` | 私聊对话 | 登录 |
| `/notifications` | 通知列表 | 登录 |
| `/search` | 全局搜索 | 公开 |
| `/leaderboard` | 排行榜 | 公开 |
| `/volunteer` | 志愿专区 | 公开 |
| `/nearby` | 附近的人 | 登录 |
| `/ngos` | 公益组织列表 | 公开 |
| `/u/<username>` | 用户公开主页 | 公开 |
| `/connect-wallet` | MetaMask 钱包绑定 | 登录 |
| `/blockchain/blocks` | 区块浏览器 | 登录 |
| `/web3` | Web3 连接状态 | 公开 |
| `/admin` | 管理后台 | 管理员 |
| `/admin/users` | 用户管理 | 管理员 |
| `/admin/moderation` | 审核中心 | 管理员 |

## 答辩演示流程

以下是建议的答辩演示顺序，覆盖所有核心功能：

### 第一部分：用户与认证（2 分钟）

1. 打开首页，展示注册页面
2. 用 `alice / test123` 登录，展示仪表盘（4 标签页 + 快捷操作）
3. 查看个人资料页（信誉分 + 评价 + 上链按钮）

### 第二部分：任务全流程（5 分钟）

4. 用 alice 发布一条新求助（展示表单字段）
5. 退出，用 `bob / test123` 登录
6. 在帮助市场找到 alice 的求助，提交帮助提议
7. 退出，重新用 alice 登录
8. 在求助详情页接受 bob 的提议（展示其他提议自动拒绝）
9. 展示私聊入口，发一条消息给 bob
10. 标记任务完成

### 第三部分：支付与评价（3 分钟）

11. 用 bob 登录，在任务详情页提交收款地址
12. 用 alice 登录，上传交易哈希（展示支付三阶段 UI）
13. 双方互评（展示对数衰减信誉公式效果）

### 第四部分：区块链审计（2 分钟）

14. 访问 `/blockchain/blocks`，展示区块列表
15. 点进区块详情，查看 Statement 记录
16. 展示信誉快照上链功能

### 第五部分：管理后台（2 分钟）

17. 用 `admin / admin123` 登录
18. 展示管理仪表盘统计
19. 展示用户管理（拉黑/解黑）
20. 展示审核中心（举报处理 + NGO 认证）

### 第六部分：其他亮点（1 分钟）

21. 搜索功能、排行榜、志愿专区、附近的人（可快速翻页展示）

## 常见问题

### 登录/注册时报错：`Install 'email_validator' for email validation support`

```bat
pip install email-validator
```

或执行 `pip install -r requirements.app.txt`。

### 附近的人页面没有结果

- 确认当前用户已在个人资料填写经纬度
- 确认筛选半径、最低信誉分与技能关键词是否过严

### 如何重置数据库

```bat
del instance\app.db
python create_admin.py
python seed_demo_data.py
python app.py
```

## 许可证

本项目采用仓库中的 `LICENSE` 文件约定。
