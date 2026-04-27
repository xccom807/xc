# DailyHelper（每日互助）项目评审与业务逻辑说明

> 更新时间：2026-04-25  
> 文档用途：项目答辩、代码交接、AI 助手快速理解项目、后续维护参考  
> 项目类型：Flask + SQLite + Solidity + Web3 的社区互助与链上托管平台

---

## 一、项目概述

DailyHelper（每日互助）是一个面向社区互助场景的 Web3 应用。平台支持用户发布求助、提交帮助申请、接受帮助、任务完成、支付结算、评价反馈、黑名单治理、申诉、链上审计、SBT 信誉凭证和 DAO 仲裁。

项目不是单纯的信息发布系统，而是一个带有资金托管和链上仲裁能力的完整互助平台。其核心目标是解决互助交易中的信任问题：

- 求助者担心付款后帮助者不履约。
- 帮助者担心完成帮助后求助者不付款。
- 平台需要对关键操作进行可追溯审计。
- 出现争议时，需要第三方可信仲裁机制。

因此项目采用了“传统 Web 后端 + 区块链托管 + 内部审计链”的混合架构。

---

## 二、技术栈

| 模块 | 技术 |
|---|---|
| 后端框架 | Flask |
| ORM | SQLAlchemy |
| 数据库 | SQLite |
| 表单 | WTForms / Flask-WTF |
| 登录认证 | Flask-Login |
| 前端渲染 | Jinja2 模板 |
| 前端交互 | 原生 JavaScript / Ethers.js v6 |
| 区块链网络 | Sepolia 测试网 |
| 智能合约 | Solidity 0.8.x |
| 合约开发 | Hardhat |
| Web3 后端 | web3.py |
| 内部审计 | Statement + Block 哈希链 |
| 样式 | 原生 CSS / SCSS |

---

## 三、整体架构

```text
浏览器
  │
  │ HTTP / Form / Fetch / MetaMask
  ▼
Flask 应用
  │
  ├── routes/auth.py          用户注册、登录、密码相关
  ├── routes/main.py          首页、仪表盘、排行榜、申诉等
  ├── routes/features.py      求助、市场、详情、帮助申请、评价、举报
  ├── routes/admin.py         管理后台、用户、支付、申诉、SBT 管理
  ├── routes/profile.py       用户主页和资料
  ├── routes/messages.py      私信系统
  ├── routes/blockchain.py    内部审计链浏览
  └── routes/api.py           钱包、SBT、Escrow、AI、Web3 API
  │
  ├── models.py               SQLAlchemy 数据模型
  ├── forms.py                WTForms 表单
  ├── blockchain_service.py   内部审计链
  ├── web3_service.py         后端 Web3 交互
  └── merkle_service.py       SBT Merkle Proof
  │
  ├── SQLite 数据库
  │     ├── User
  │     ├── HelpRequest
  │     ├── HelpOffer
  │     ├── Payment
  │     ├── Review
  │     ├── WalletLink
  │     ├── Statement
  │     ├── Block
  │     └── Appeal
  │
  └── Sepolia 智能合约
        ├── ReputationSBT.sol
        └── TaskEscrow.sol
```

---

## 四、核心业务流程

### 4.1 普通互助流程

```text
用户注册 / 登录
  ↓
发布求助 HelpRequest(open)
  ↓
其他用户提交帮助申请 HelpOffer(pending)
  ↓
求助者接受某个申请 HelpOffer(accepted)
  ↓
任务进入进行中 HelpRequest(in_progress)
  ↓
帮助者完成服务
  ↓
求助者确认完成 / 释放赏金
  ↓
HelpRequest(completed)
  ↓
双方评价
```

### 4.2 付费任务 Escrow 流程

付费任务不是简单记录“待支付/已支付”，而是通过 `TaskEscrow` 合约托管资金。

```text
求助者接受帮助申请
  ↓
前端调用 TaskEscrow.createEscrow(taskId, helper)
  ↓
ETH 锁入合约
  ↓
后端同步 HelpRequest(in_progress)
  ↓
任务完成后：
  ├── 求助者认可 → releaseToHelper → 帮助者收款
  └── 出现争议 → raiseDispute → DAO 仲裁
```

### 4.3 DAO 仲裁流程

```text
任务进入争议 HelpRequest(disputed)
  ↓
金牌 SBT 用户进入仲裁大厅
  ↓
调用 voteOnDispute(taskId, choice)
  ↓
达到投票阈值后合约自动结算
  ↓
结果一：PayHelper
      - 资金扣除手续费后打给帮助者
      - 后端同步 Payment(paid)
      - HelpRequest(completed)

结果二：RefundRequester
      - 资金扣除手续费后退给求助者
      - 后端同步 Payment(refunded)
      - HelpRequest(cancelled)
```

---

## 五、关键数据模型

### 5.1 User

用户模型，包含登录信息、信誉分、角色、黑名单状态、头像、地理位置和个人资料。

关键字段：

- `username`
- `email`
- `password_hash`
- `reputation_score`
- `user_type`
- `is_blacklisted`
- `lat`
- `lng`
- `skills`

### 5.2 HelpRequest

求助任务模型，是平台业务的核心。

关键字段：

- `title`
- `description`
- `category`
- `location`
- `price`
- `is_volunteer`
- `status`

状态含义：

| 状态 | 含义 |
|---|---|
| `open` | 已发布，等待帮助者申请 |
| `in_progress` | 已接受帮助，任务进行中 |
| `completed` | 任务完成，资金已支付给帮助者 |
| `cancelled` | 任务取消，或仲裁退款给求助者 |
| `disputed` | 任务争议中，等待仲裁 |

### 5.3 HelpOffer

帮助申请模型。

状态含义：

| 状态 | 含义 |
|---|---|
| `pending` | 等待求助者处理 |
| `accepted` | 已被接受 |
| `rejected` | 已被拒绝 |
| `completed` | 对应帮助最终完成 |

### 5.4 Payment

支付记录模型，用于记录链下支付或链上 Escrow 同步后的结算结果。

状态含义：

| 状态 | 含义 |
|---|---|
| `address_submitted` | 帮助者已提交收款地址，等待支付 |
| `paid` | 已支付给帮助者 |
| `refunded` | 仲裁后已退款给求助者 |

需要特别注意：字段名 `helper_address` 历史上表示“收款地址”。为了兼容旧模型，在退款场景下该字段保存“退款地址”。管理员页面已改为显示“收款/退款地址”。

### 5.5 WalletLink

钱包绑定模型，用于保存用户绑定和验证过的钱包地址。

### 5.6 Statement / Block

内部审计链模型。关键业务操作会写入 `Statement`，多个 Statement 可以封装成 `Block`，形成 SQLite 内部哈希链，并可选锚定到 Sepolia。

### 5.7 Appeal

黑名单申诉模型。黑名单用户可以提交申诉，管理员可以审核通过或拒绝。

---

## 六、智能合约说明

### 6.1 ReputationSBT.sol

`ReputationSBT` 是灵魂绑定信誉凭证合约，主要用途是把平台信誉等级映射为链上不可转让 SBT。

特点：

- ERC-721 形式。
- 不允许普通转账。
- 使用 Merkle Proof 控制 Mint 资格。
- 支持不同信誉等级。
- 仲裁合约通过它判断用户是否具备金牌仲裁资格。

### 6.2 TaskEscrow.sol

`TaskEscrow` 是任务资金托管合约。

核心状态：

| 链上状态 | 数值 | 含义 |
|---|---:|---|
| `None` | 0 | 不存在 |
| `Locked` | 1 | 资金已锁定 |
| `Completed` | 2 | 求助者主动释放给帮助者 |
| `Disputed` | 3 | 争议中 |
| `Resolved` | 4 | 仲裁已解决 |

投票选择：

| 选择 | 数值 | 含义 |
|---|---:|---|
| `None` | 0 | 未投票 |
| `PayHelper` | 1 | 支持打款给帮助者 |
| `RefundRequester` | 2 | 支持退款给求助者 |

核心函数：

- `createEscrow(taskId, helper)`
- `releaseToHelper(taskId)`
- `raiseDispute(taskId)`
- `voteOnDispute(taskId, choice)`
- `getEscrow(taskId)`
- `setFeeBasisPoints(fee)`
- `withdrawFees(to)`

### 6.3 手续费规则

当前合约设计为：无论资金最终给帮助者，还是仲裁退款给求助者，都扣除平台手续费。

也就是说：

```text
托管金额：1 ETH
手续费率：5%
实际到账：0.95 ETH
平台手续费：0.05 ETH
```

该逻辑在合约中通过 `_deductFee(e.amount)` 实现，帮助者胜出和求助者胜出都会调用该函数。

这是当前项目确认采用的业务规则，因此不需要修改合约。

---

## 七、Escrow / 支付 / 仲裁状态映射

这部分是项目中最关键、也是最容易出错的业务逻辑。

### 7.1 链上状态到后端状态

| 链上动作 | 链上状态 | 后端 HelpRequest | Payment | 说明 |
|---|---|---|---|---|
| `createEscrow` | `Locked` | `in_progress` | 可无记录 | 赏金已锁定 |
| `releaseToHelper` | `Completed` | `completed` | `paid` | 求助者主动释放赏金 |
| `raiseDispute` | `Disputed` | `disputed` | 不改变或暂无 | 进入仲裁 |
| 仲裁 `PayHelper` | `Resolved` | `completed` | `paid` | 仲裁判帮助者胜 |
| 仲裁 `RefundRequester` | `Resolved` | `cancelled` | `refunded` | 仲裁判求助者胜 |

### 7.2 为什么不能只看链上 status

链上 `Resolved` 只表示“仲裁已经解决”，但不表示“谁赢了”。

错误逻辑是：

```text
status == Resolved
  ↓
显示支付成功
```

正确逻辑是：

```text
status == Resolved
  ↓
读取 votesForHelper 和 votesForRequester
  ↓
votesForHelper > votesForRequester
    → 帮助者胜出，显示支付成功
  ↓
votesForRequester >= votesForHelper
    → 求助者胜出，显示仲裁退款
```

本项目已经修复该问题。

---

## 八、本次重点修复内容

### 8.1 修复仲裁退款仍显示“支付成功”

原问题：

- 详情页把链上 `status === 4` 直接当成“Escrow 已结算给帮助者”。
- 但 `status === 4` 实际只代表“争议已裁决”。
- 如果裁决结果是退款给求助者，页面仍然显示支付成功，业务含义错误。

修复后：

- `status === 2`：求助者主动释放，显示“已打款给帮助者”。
- `status === 4` 且帮助者票数更多：显示“仲裁打款给帮助者”。
- `status === 4` 且求助者票数更多或相等：显示“仲裁退款给求助者”。

涉及文件：

- `templates/features/request_detail.html`
- `templates/features/arbitration.html`
- `routes/api.py`

### 8.2 后端不再盲信前端 outcome

原问题：

- 前端调用 `/api/escrow/sync` 时传入 `outcome`。
- 后端直接根据前端传入的 `outcome` 修改数据库。
- 如果有人伪造请求，理论上可以把数据库同步成错误状态。

修复后：

- 当 `action == "resolve"` 时，后端会调用链上 `getEscrow(taskId)`。
- 后端确认链上状态必须是 `Resolved`。
- 后端根据链上票数决定结果。
- 前端传入的 `outcome` 不再作为仲裁结果的可信来源。

这是非常重要的安全修复。

### 8.3 退款也创建 Payment 记录

原问题：

- 只有帮助者胜出时创建 `Payment(status='paid')`。
- 求助者胜出时，如果没有已有 Payment，后台可能没有清晰记录。

修复后：

- 求助者胜出也会创建或更新 `Payment(status='refunded')`。
- 管理员可以在支付记录中看到“已退款”。
- 详情页可以根据 `refunded` 正确显示退款状态。

### 8.4 管理后台支付页支持 refunded

原问题：

- 管理员支付页只认识“待支付”和“已支付”。
- 仲裁退款无法准确展示。

修复后：

- 筛选项新增“已退款”。
- 状态列新增“已退款”徽章。
- 地址列改为“收款/退款地址”。

涉及文件：

- `templates/admin/payments.html`

### 8.5 防止 Escrow 付费任务被普通取消

原问题：

- 付费任务进入 `in_progress` 后，赏金可能已经锁入 Escrow。
- 如果此时允许普通取消，数据库会变成取消状态，但链上资金仍然锁着。
- 这会造成链上和数据库严重不一致。

修复后：

- 付费且非志愿任务进入 `in_progress` 后，不能走普通取消。
- 必须通过：
  - 求助者释放赏金。
  - 或进入仲裁，由合约退款/打款。

涉及文件：

- `routes/features.py`
- `templates/features/request_detail.html`

### 8.6 链上状态读取失败时不再显示危险按钮

原问题：

- 如果前端读取链上状态失败，会同时显示“释放赏金 / 发起仲裁 / 锁定赏金”等按钮。
- 这容易造成误操作。

修复后：

- 如果无法读取链上 Escrow 状态，页面只显示错误提示。
- 不再展示资金操作按钮。

---

## 九、黑名单与申诉机制

项目已经补充黑名单相关治理能力。

### 9.1 黑名单限制

黑名单用户会被限制执行以下操作：

- 发送私信。
- 提交评价。
- 举报内容。
- 提交支付地址。

登录时会提示用户当前处于黑名单状态，并提供申诉入口。

### 9.2 申诉流程

```text
黑名单用户
  ↓
访问申诉页面
  ↓
提交申诉理由
  ↓
管理员后台查看申诉
  ↓
管理员审核通过或拒绝
  ↓
通过后解除黑名单
```

涉及文件：

- `models.py`
- `forms.py`
- `routes/main.py`
- `routes/admin.py`
- `templates/appeal.html`
- `templates/admin/appeals.html`

---

## 十、志愿服务页面整合

项目原本存在独立 `/volunteer` 页面，但其功能和市场页面高度重复。

当前设计为：

- 志愿服务不再作为完全独立的信息架构。
- 志愿任务整合到 `/marketplace`。
- 市场页面支持志愿筛选和志愿统计展示。
- `/volunteer` 路由可重定向到市场页的志愿筛选结果。

这样可以减少重复页面，避免同一类任务在两个入口维护两套逻辑。

---

## 十一、项目亮点

### 11.1 完整的互助交易闭环

项目覆盖了从发布求助到评价结束的完整流程，并且包含异常处理：

- 发布求助。
- 帮助申请。
- 接受申请。
- 私信沟通。
- 任务执行。
- 支付或托管。
- 仲裁。
- 评价。
- 举报。
- 黑名单。
- 申诉。

### 11.2 Web2 + Web3 混合架构

项目不是为了上链而上链，而是把链上能力放在真正需要可信执行的地方：

- 钱包绑定。
- SBT 信誉凭证。
- Escrow 资金托管。
- DAO 仲裁。
- 审计锚定。

普通列表、搜索、聊天、后台管理仍然留在传统 Web 后端，提高开发效率和用户体验。

### 11.3 内部审计链

除了 Sepolia 合约，项目还有内部 `Statement → Block` 审计链。

关键操作会记录为 Statement，例如：

- 用户注册。
- 登录。
- 发布求助。
- 接受帮助。
- 支付同步。
- 仲裁同步。
- 管理员操作。

这使项目具备较好的可追溯性。

### 11.4 SBT 仲裁资格控制

仲裁不是任意用户都能参与，而是通过 ReputationSBT 进行资格判断。

只有具备对应信誉等级的用户才能进行仲裁投票，提高了仲裁可信度。

---

## 十二、当前仍需注意的风险

### 12.1 没有数据库迁移框架

项目目前主要依赖 `db.create_all()` 或脚本迁移。

风险：

- 修改模型后，旧数据库不会自动新增字段。
- 演示环境和开发环境可能出现结构不一致。

建议：

- 引入 Flask-Migrate / Alembic。
- 或在答辩前固定使用全新初始化数据库。

### 12.2 Payment 模型字段命名存在历史包袱

`Payment.helper_address` 在退款场景下保存退款地址，字段名不够准确。

当前为了兼容旧数据库没有改字段名，但更合理的长期设计是：

- `recipient_address`
- `recipient_role`
- `settlement_type`

### 12.3 Escrow 合约变更需要重新部署

当前合约规则已经确认：

- 帮助者胜出扣手续费。
- 求助者退款也扣手续费。

如果未来要改成“退款不扣手续费”，必须修改合约、重新测试、重新部署，并更新前端合约地址。

### 12.4 后端链上同步依赖 RPC

现在后端会验证链上仲裁结果，这是正确的安全策略，但也意味着：

- RPC 配置错误会导致同步失败。
- Sepolia 节点不可用会影响页面状态同步。

建议：

- 使用稳定 RPC 服务。
- 在生产环境增加重试和后台任务同步。

### 12.5 前端仍是传统模板模式

项目采用 Jinja2 服务端渲染，适合课程项目和快速开发。

但 Web3 状态交互比较复杂，长期可以考虑：

- 用 Alpine.js 简化状态管理。
- 或将 Web3 交互页面拆成更独立的前端组件。

---

## 十三、建议演示顺序

### 13.1 基础平台能力

1. 注册 / 登录。
2. 发布求助。
3. 市场筛选。
4. 提交帮助申请。
5. 接受帮助。
6. 私信沟通。

### 13.2 Web3 能力

1. 绑定钱包。
2. 查看 SBT 资格。
3. 创建 Escrow 托管。
4. 释放赏金。
5. 查看支付记录。

### 13.3 仲裁能力

1. 发起争议。
2. 金牌用户进入仲裁大厅。
3. 投票支持帮助者或求助者。
4. 达到阈值后自动结算。
5. 展示详情页正确显示：
   - 打款给帮助者。
   - 或退款给求助者。

### 13.4 治理能力

1. 管理员拉黑用户。
2. 黑名单用户登录看到提示。
3. 用户提交申诉。
4. 管理员审核申诉。

### 13.5 审计能力

1. 查看内部区块链浏览器。
2. 展示 Statement。
3. 展示 Block 哈希链。
4. 展示可选 Sepolia 锚定。

---

## 十四、关键文件索引

| 文件 | 职责 |
|---|---|
| `app.py` | Flask 应用工厂、Blueprint 注册、兼容路由 |
| `models.py` | 数据模型 |
| `forms.py` | 表单定义 |
| `routes/features.py` | 求助、市场、任务详情、申请、取消、评价、举报 |
| `routes/api.py` | 钱包、支付、Escrow 同步、SBT、Web3、AI |
| `routes/admin.py` | 管理后台、支付、申诉、用户治理 |
| `routes/main.py` | 首页、仪表盘、排行榜、申诉入口 |
| `routes/messages.py` | 私信系统 |
| `routes/blockchain.py` | 内部审计链浏览 |
| `templates/features/request_detail.html` | 任务详情、支付状态、Escrow 操作展示 |
| `templates/features/arbitration.html` | 仲裁大厅 |
| `templates/admin/payments.html` | 管理员支付记录 |
| `contracts/src/TaskEscrow.sol` | Escrow 托管和仲裁合约 |
| `contracts/src/ReputationSBT.sol` | 信誉 SBT 合约 |
| `static/js/web3-integration.js` | 前端 Web3 交互 |
| `blockchain_service.py` | 内部审计链 |
| `web3_service.py` | 后端 Web3 服务 |
| `merkle_service.py` | SBT Merkle Proof |

---

## 十五、环境与运行

### 15.1 Python 环境

```powershell
python -m venv myenv
.\myenv\Scripts\activate
pip install -r requirements.txt
```

### 15.2 初始化数据

```powershell
python create_admin.py
python seed_demo_data.py
```

### 15.3 启动项目

```powershell
python app.py
```

或：

```powershell
.\run_app.bat
```

默认访问：

```text
http://127.0.0.1:5000
```

### 15.4 合约测试

需要在 `contracts` 目录下执行：

```powershell
npm install
npx hardhat test
```

---

## 十六、答辩时可以强调的点

### 16.1 项目不是简单 CRUD

项目包含完整业务状态机，尤其是：

- 求助状态。
- 帮助申请状态。
- 支付状态。
- Escrow 链上状态。
- 仲裁结果状态。

这些状态必须互相映射，否则就会出现“链上退款但页面显示支付成功”的严重问题。

### 16.2 资金结果以后端链上验证为准

本项目已经修复为：

- 前端只负责触发和展示。
- 后端同步仲裁结果时必须读取链上状态。
- 数据库状态不能只相信前端传参。

这体现了 Web3 项目中非常重要的原则：

```text
前端不可信，链上结果才可信。
```

### 16.3 仲裁退款也扣手续费是明确业务规则

当前合约设计为：

- 打款给帮助者扣手续费。
- 退款给求助者也扣手续费。

这是平台服务费规则的一部分，不是 bug。

### 16.4 平台治理闭环完整

除了交易流程，项目还实现了治理能力：

- 举报。
- 黑名单。
- 黑名单功能限制。
- 用户申诉。
- 管理员审核。

这让平台不仅能交易，也能维护社区秩序。

---

## 十七、综合评价

DailyHelper 项目已经具备较完整的产品形态和技术深度。它不是单一 Flask CRUD 应用，而是结合了：

- 传统 Web 业务系统。
- 区块链资金托管。
- SBT 信誉凭证。
- DAO 仲裁。
- 内部审计链。
- 管理后台。
- 黑名单与申诉治理。

本次重点修复后，Escrow、Payment、Arbitration 三者之间的状态映射更加一致，尤其修复了仲裁退款被误显示为支付成功的问题。

当前项目适合作为毕业设计、课程项目或 Web3 应用原型进行展示。后续如果要继续提升，优先方向应是：

1. 引入数据库迁移体系。
2. 为 Escrow 同步和仲裁状态增加自动化测试。
3. 优化前端 Web3 状态管理。
4. 将 Payment 模型升级为更通用的 Settlement 模型。
5. 增加后台异步链上同步任务。

---

## 十八、给后续 AI 助手的上下文摘要

如果后续由 AI 助手继续维护本项目，需要优先理解以下事实：

1. 项目是 Flask Blueprint 架构，主要业务在 `routes/features.py` 和 `routes/api.py`。
2. 任务主模型是 `HelpRequest`，申请模型是 `HelpOffer`，支付模型是 `Payment`。
3. 付费任务使用 `TaskEscrow.sol` 托管资金。
4. 链上 `Completed` 表示求助者主动释放赏金给帮助者。
5. 链上 `Resolved` 只表示仲裁已结束，不代表一定支付给帮助者。
6. 仲裁结果必须根据链上票数判断。
7. 后端 `/api/escrow/sync` 在 `resolve` 时必须读取链上结果，不能信任前端 outcome。
8. `Payment.status` 当前支持 `address_submitted`、`paid`、`refunded`。
9. 仲裁退款也扣平台手续费，这是当前业务规则。
10. 付费 `in_progress` 任务不能普通取消，否则会造成链上资金和数据库状态不一致。
11. 黑名单用户已经被限制私信、评价、举报和提交支付地址。
12. 用户可以通过申诉流程请求管理员解除黑名单。
13. 修改模型后要注意 SQLite 无自动迁移问题。
14. 前端 Web3 页面主要在 `request_detail.html`、`arbitration.html` 和 `static/js/web3-integration.js`。
15. 项目文本和交互语言以中文为主。

---

## 十九、主要路由一览

### 19.1 公开页面

| 路由 | 说明 |
|---|---|
| `/` | 首页 |
| `/about` | 关于页面 |
| `/signup` | 注册 |
| `/login` | 登录 |
| `/marketplace` | 帮助市场，支持分类、地点、价格、志愿筛选 |
| `/search` | 全局搜索 |
| `/leaderboard` | 排行榜 |
| `/volunteer` | 志愿服务入口，当前整合至市场页 |
| `/u/<username>` | 用户公开主页 |
| `/chatbot` | AI 智能助手 |
| `/web3` | Web3 状态、余额查询、手动锚定 |

### 19.2 用户页面

| 路由 | 说明 |
|---|---|
| `/dashboard` | 用户仪表盘 |
| `/request-help` | 发布求助 |
| `/offer-help` | 浏览可帮助的求助 |
| `/requests/<id>` | 求助详情，包含申请、接受、Escrow、支付、评价 |
| `/requests/<id>/cancel` | 取消求助，付费 Escrow 进行中任务不可直接取消 |
| `/my-offers` | 我的帮助记录 |
| `/messages` | 私信收件箱 |
| `/messages/<user_id>` | 与指定用户私聊 |
| `/notifications` | 通知列表 |
| `/settings/profile` | 编辑个人资料 |
| `/nearby` | 附近的人 |
| `/flag` | 举报 |
| `/appeal` | 黑名单申诉 |
| `/connect-wallet` | 绑定 MetaMask 钱包 |
| `/my-wallets` | 我的钱包列表 |
| `/blockchain/blocks` | 内部区块链浏览器 |
| `/blockchain/reputation/anchor` | 信誉快照上链 |
| `/blockchain/reputation/proof/<username>` | 可验证信誉 JSON |
| `/arbitration` | DAO 仲裁大厅 |

### 19.3 管理员页面

| 路由 | 说明 |
|---|---|
| `/admin` | 管理后台首页 |
| `/admin/users` | 用户管理、拉黑、解黑 |
| `/admin/requests` | 求助管理 |
| `/admin/moderation` | 举报审核 |
| `/admin/payments` | 支付记录，支持待支付、已支付、已退款 |
| `/admin/broadcast` | 发布公告 |
| `/admin/appeals` | 用户申诉审核 |
| `/admin/export/users` | 导出用户 CSV |
| `/admin/export/requests` | 导出求助 CSV |
| `/admin/sbt` | SBT 信誉代币管理 |

### 19.4 API 接口

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/chatbot` | POST | AI 聊天接口 |
| `/api/submit-payment-address` | POST | 帮助者提交收款地址 |
| `/api/record-payment` | POST | 求助者上传支付凭证 |
| `/wallet/challenge` | POST | 钱包验证挑战 |
| `/wallet/verify` | POST | 钱包签名验证 |
| `/web3/balance` | GET | 查询以太坊地址余额 |
| `/api/sbt/proof` | GET | 获取当前用户的 Merkle Proof |
| `/api/sbt/status/<addr>` | GET | 查询钱包地址 SBT 状态 |
| `/api/escrow/sync` | POST | Escrow 链上状态同步，仲裁 resolve 时以后端链上读取结果为准 |
| `/api/contracts/config` | GET | 获取合约地址和链配置 |

---

## 附录：全流程测试教程

> 按顺序执行以下步骤，可以完整体验所有 Web2 + Web3 功能。

---

## 0. 环境准备

### 0.1 启动应用

```bash
cd d:\bise\Kaspersky-519-WT-05-main

# 方式一：使用批处理（推荐，会自动设置环境变量）
run_app.bat

# 方式二：手动启动
myenv\Scripts\activate
python app.py
```

应用地址：**http://127.0.0.1:5000**

### 0.2 重置数据库（可选，从全新状态开始）

```bash
myenv\Scripts\python create_admin.py
myenv\Scripts\python seed_demo_data.py
```

### 0.3 MetaMask 准备

- 安装 MetaMask 浏览器扩展
- 切换到 **Sepolia 测试网**
- 确保账户有少量 Sepolia ETH（可从 [Sepolia Faucet](https://sepoliafaucet.com/) 领取）

### 0.4 测试账号一览

| 用户 | 邮箱 | 密码 | 角色 | 信誉分 |
|------|------|------|------|--------|
| admin | admin@dailyhelper.com | admin123 | 管理员 | 100 |
| alice | alice@test.com | test123 | 普通用户 | 5.8 |
| bob | bob@test.com | test123 | 普通用户 | 9.8 |
| charlie | charlie@test.com | test123 | 普通用户 | 0 |
| expert1 | expert1@test.com | test123 | 专家用户 | 85 |
| expert2 | expert2@test.com | test123 | 专家用户 | 85 |
| expert3 | expert3@test.com | test123 | 专家用户 | 85 |

---

## 第一部分：基础 Web2 功能

### 1. 注册与登录

1. 打开 http://127.0.0.1:5000/signup
2. 注册一个新账号（如 `tester / tester@test.com / test123`）
3. 注册成功后自动跳转到仪表盘
4. 点击导航栏 **退出**
5. 打开 http://127.0.0.1:5000/login，用刚才的账号登录
6. 验证：成功进入仪表盘页面

### 2. 个人资料编辑

1. 点击导航栏 **我的资料**
2. 点击 **编辑资料** 按钮
3. 修改全名、位置、简介、技能等字段
4. 保存，验证：资料页面显示更新后的内容

### 3. 发布求助（免费志愿任务）

1. 登录 `alice` 账号
2. 点击仪表盘的 **发布求助**
3. 填写表单：
   - 标题：`帮忙遛狗`
   - 描述：`下午3点需要人帮忙遛金毛，公园附近`
   - 分类：`生活服务`
   - 勾选 **志愿服务**（不填价格）
4. 提交，验证：跳转到任务详情页，状态为 `Open`，显示「志愿服务」标签

### 4. 发布求助（付费任务）

1. 仍然用 `alice` 账号
2. 再次 **发布求助**：
   - 标题：`Python 作业辅导`
   - 描述：`需要帮忙调试一个 Flask 项目`
   - 分类：`编程`
   - **不勾选** 志愿服务
   - 价格填 `0.05`
3. 提交，验证：任务详情页显示 `0.05` 价格标签

### 5. 提交帮助申请

1. **退出** alice，登录 `bob`
2. 打开 http://127.0.0.1:5000/marketplace，找到 alice 刚发的 `Python 作业辅导`
3. 点击进入任务详情
4. 在右侧「提供你的帮助」区域填写留言，提交
5. 验证：页面显示「您已提交过帮助申请，状态: Pending」

### 6. 接受帮助申请（普通方式）

1. **退出** bob，登录 `alice`
2. 进入 `帮忙遛狗` 任务详情
3. 在「收到的帮助申请」列表中，点击 **接受帮助申请**
4. 验证：任务状态变为 `In_progress`

### 7. 完成任务 + 互相评价

1. 仍然在 `帮忙遛狗` 详情页（alice 视角）
2. 点击 **标记任务已完成**
3. 任务状态变为 `Completed`
4. 在页面底部「提交评价」区域，给 bob 打分并写评语
5. **退出** alice，登录 `bob`
6. 进入同一任务，提交对 alice 的评价
7. 验证：双方评价都显示在评价列表中

### 8. 私信功能

1. 登录 `alice`
2. 点击导航栏 **私信**
3. 或进入 bob 的个人主页 http://127.0.0.1:5000/u/bob，点击 **发送私信**
4. 发送一条消息
5. 切换到 `bob` 账号，查看私信列表，回复
6. 验证：双方都能看到聊天记录

### 9. 搜索与排行榜

1. 点击导航栏 **搜索**，输入关键词搜索任务
2. 点击导航栏 **排行榜**，查看信誉排名
3. 验证：expert1/expert2/expert3 排名靠前

### 10. 通知系统

1. 登录 `alice`，点击导航栏 **通知**
2. 验证：能看到之前的操作通知（如 bob 提交帮助申请、任务完成等）

### 11. 举报功能

1. 登录 `bob`，进入任意他人发布的任务
2. 点击 **举报** 按钮
3. 填写举报理由并提交
4. 验证：提示举报已提交

---

## 第二部分：管理后台

### 12. 管理员登录

1. 登录管理员账号：`admin@dailyhelper.com / admin123`
2. 自动跳转到管理后台 http://127.0.0.1:5000/admin

### 13. 用户管理

1. 点击 **用户管理**
2. 查看所有用户列表
3. 尝试 **拉黑** 某个用户（如 eve），再 **解除拉黑**

### 14. 任务管理

1. 点击 **任务管理**
2. 查看所有任务列表
3. 可以强制取消某个任务

### 15. 内容审核

1. 点击 **内容审核**
2. 查看之前的举报记录
3. 处理举报（忽略 / 处理）

### 16. 数据导出

1. 在管理后台点击 **导出用户数据** 或 **导出任务数据**
2. 验证：下载 CSV 文件

---

## 第三部分：区块链审计链（内部链）

### 17. 查看区块链浏览器

1. 登录任意用户
2. 访问 http://127.0.0.1:5000/blockchain/blocks
3. 查看已封装的区块列表
4. 点击某个区块查看其中的 statements
5. 验证：能看到注册、登录、创建任务等操作的链上记录

### 18. 信誉快照上链

1. 登录 `expert1`
2. 访问 http://127.0.0.1:5000/u/expert1
3. 在「链上信誉证明」区域点击 **将当前信誉快照上链**
4. 等待交易确认（需要 Sepolia ETH）
5. 验证：页面显示交易哈希和上链时间
6. 点击 **查看可验证快照(JSON)** 查看完整快照数据

---

## 第四部分：Web3 钱包绑定

### 19. 连接 MetaMask

1. 登录 `alice`（或用你自己的账号）
2. 点击导航栏 **连接 MetaMask**
3. MetaMask 弹出请求，选择账户并确认
4. 签名验证消息
5. 验证：按钮变为「已连接: 0xABC...1234」

### 20. 查看钱包绑定状态

1. 访问 http://127.0.0.1:5000/connect-wallet
2. 验证：页面显示已绑定的钱包地址和链 ID

---

## 第五部分：SBT 灵魂绑定代币

### 21. 管理员生成 Merkle Root

1. 登录 `admin@dailyhelper.com / admin123`
2. 进入 http://127.0.0.1:5000/admin/sbt
3. 查看「合格用户列表」（信誉 ≥ 20 且已绑定钱包的用户）
4. 点击 **生成 Merkle Root 并上链**
5. 等待交易确认
6. 验证：页面显示成功消息和 Tx Hash

> **注意**：此操作消耗服务端签名者的 Sepolia ETH（config.py 中的 `ETH_SIGNER_PRIVATE_KEY`）

### 22. 用户铸造 SBT

1. 登录 `expert1`（信誉 85，已绑定钱包 `0x27492d60...`）
2. 确保 MetaMask 当前账户是 `0x27492d60061B7A66154F828CCC7e68512f340188`
3. 访问 http://127.0.0.1:5000/u/expert1
4. 在「灵魂绑定代币 (SBT)」区域，点击 **申领 / 升级 SBT**
5. MetaMask 弹窗确认交易
6. 等待交易确认
7. 验证：SBT 状态显示「🥇 金牌 (链上分: 85)」

> **前提**：步骤 21 必须先完成（链上有 Merkle Root 才能验证 Proof）

---

## 第六部分：Escrow 赏金托管

### 23. 发布付费任务 → 接受 → 锁定 Escrow

1. 登录 `alice`
2. **发布求助**：标题 `Escrow测试任务`，价格 `0.01`，不勾选志愿
3. **退出**，登录 `bob`
4. 找到该任务，提交帮助申请
5. **退出**，登录 `alice`
6. 进入任务详情，在帮助申请列表找到 bob 的申请
7. 如果 bob 已绑定钱包，会看到 **「接受并锁定赏金」** 按钮
8. 点击按钮 → MetaMask 弹窗确认 → 支付 0.01 ETH
9. 等待交易确认
10. 验证：
    - 任务状态变为 `In_progress`
    - 链上托管状态显示「⛓️ 已锁定 | 0.01 ETH」

### 24. 释放赏金（正常完成）

1. 仍在 alice 的任务详情页
2. 任务管理区域现在显示 **「确认完成并释放赏金」** 和 **「发起仲裁」**
3. 点击 **确认完成并释放赏金**
4. MetaMask 确认交易
5. 验证：
    - 任务状态变为 `Completed`
    - 链上托管状态显示「✅ Escrow 已结算」
    - bob 的 Sepolia 钱包收到 0.01 ETH

---

## 第七部分：DAO 仲裁

### 25. 创建争议任务

1. 登录 `alice`，发布新付费任务，价格 `0.01`
2. 登录 `bob`，提交帮助申请
3. 登录 `alice`，接受并锁定赏金（同步骤 23）
4. 锁定成功后，页面刷新，点击 **「发起仲裁」**
5. MetaMask 确认交易
6. 验证：任务状态变为 `Disputed`，显示「⚖️ 仲裁中」

### 26. 专家投票

1. 登录 `expert1`（信誉 85，有 SBT 金牌）
2. 导航栏出现 **仲裁大厅** 入口，点击进入
3. 看到争议任务列表
4. 点击 **「支持打款」**（资金释放给帮助者）或 **「支持退款」**（退给求助者）
5. MetaMask 确认交易
6. 验证：
    - DAO_VOTE_THRESHOLD 默认为 1，一票即可裁决
    - 投票完成后任务自动结算
    - 链上状态变为「已裁决」

> **重要**：投票者的 MetaMask 地址 **不能** 是任务的求助者或帮助者，否则合约会拒绝。

---

## 第八部分：补充功能

### 27. 智能助手（AI 聊天）

1. 点击导航栏 **智能助手**
2. 输入问题，如「如何发布求助？」
3. 验证：收到 AI 回复

### 28. 附近的人

1. 登录任意有位置信息的用户
2. 点击 **附近的人**
3. 验证：显示按距离排序的用户列表

### 29. 志愿服务专区

1. 访问 http://127.0.0.1:5000/volunteer
2. 验证：页面跳转或整合到市场页，并通过志愿筛选查看志愿服务任务

---

## 快速验证清单

完成以上步骤后，确认以下功能全部正常：

| # | 功能 | 验证点 |
|---|------|--------|
| ✅ | 注册 / 登录 / 退出 | 正常跳转 |
| ✅ | 发布免费任务 | 显示志愿标签 |
| ✅ | 发布付费任务 | 显示 ETH 价格 |
| ✅ | 提交帮助申请 | 状态 Pending |
| ✅ | 接受帮助申请 | 状态 In_progress |
| ✅ | 完成任务 | 状态 Completed |
| ✅ | 互相评价 | 评分显示 |
| ✅ | 私信聊天 | 双向消息 |
| ✅ | 搜索 / 排行榜 | 结果正确 |
| ✅ | 通知系统 | 有通知记录 |
| ✅ | 管理后台 | 用户 / 任务 / 审核 |
| ✅ | 区块链审计 | 区块列表 + statements |
| ✅ | MetaMask 绑定 | 签名验证成功 |
| ✅ | SBT 铸造 | 链上等级显示 |
| ✅ | Escrow 锁定 | 链上状态：已锁定 |
| ✅ | Escrow 释放 | 帮助者收款 |
| ✅ | DAO 仲裁投票 | 自动裁决 + 结算 |

---

## 合约地址（Sepolia 测试网）

| 合约 | 地址 |
|------|------|
| ReputationSBT | `0xC80713Ae1aB233BB29b9991a80BA7594f5C128F3` |
| TaskEscrow | `0x90413AfD18C53172d09caD650FB5Fd80b7154002` |

Etherscan 查看：
- SBT: https://sepolia.etherscan.io/address/0xC80713Ae1aB233BB29b9991a80BA7594f5C128F3
- Escrow: https://sepolia.etherscan.io/address/0x90413AfD18C53172d09caD650FB5Fd80b7154002

---

## 许可证

本项目采用仓库中的 `LICENSE` 文件约定。

