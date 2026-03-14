# Kaspersky-519-WT-05（每日互助 / DailyHelper）

一个基于 Flask 的社区互助平台，支持用户发布求助、提交帮助提议、任务协作与评价，并集成了“内部区块链式审计日志”与可选 Web3 连接能力。  
本 README 基于当前仓库代码结构与实现重新整理，可直接用于项目接手、部署与二次开发。

## 目录

- [项目概览](#项目概览)
- [核心功能](#核心功能)
- [技术栈与架构](#技术栈与架构)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [运行与使用示例](#运行与使用示例)
- [开发指南](#开发指南)
- [贡献规范](#贡献规范)
- [常见问题](#常见问题)
- [许可证](#许可证)

## 项目概览

### 定位

“每日互助”用于连接“需要帮助的人”和“愿意提供帮助的人”，并提供以下能力：

- 求助发布与浏览（付费/志愿两类）
- 提议、接单、任务完成闭环
- 双向评价与信誉分
- 公益组织（NGO）展示与提交审核
- 管理员审核、封禁与内容治理
- 内部审计链（Statement -> Block）可视化追踪
- 可选 Web3 RPC 连接状态与链上区块查看

### 当前实现形态

- 后端：单体 Flask 应用，应用工厂模式 `create_app()`
- 数据层：Flask-SQLAlchemy + SQLite（默认）
- 前端：Jinja2 模板 + 原生 CSS/JS
- 鉴权：Flask-Login + Flask-WTF（含 CSRF）

## 核心功能

### 用户与身份

- 注册/登录/退出
- 个人资料编辑（含技能、简介、头像 URL、经纬度）
- 公开个人主页（历史评价、信誉层级、完成率）

### 互助任务

- 发布求助（分类、描述、地点、时段、预算、志愿选项）
- 市场页筛选检索（分类/地点/价格区间/日期/排序）
- 求助详情页：
  - 提交帮助提议
  - 求助方接受某个提议（其余自动拒绝）
  - 标记任务完成
  - 双方评价与信誉分变更

### 志愿与社区

- 志愿服务专区（仅志愿任务）
- 附近的人（根据经纬度 + Haversine 距离计算）
- NGO 列表、详情、提交与后台审核

### 管理后台

- 管理仪表盘（用户、任务、标记统计）
- 用户管理（搜索、拉黑、解除拉黑、删除）
- 审核中心（Flag 处理、NGO 验证）

### 区块链相关能力

- 内部审计链：
  - 应用行为记录为 `Statement`
  - 达到阈值后封装为 `Block`（哈希链）
- 区块浏览页面：`/blockchain/blocks`
- 区块观察脚本：`watch_blocks.py`
- 可选 Web3 RPC：`/web3`、`/web3/balance`

## 技术栈与架构

### 后端

- Flask 3.x
- Flask-SQLAlchemy / SQLAlchemy 2.x
- Flask-Login
- Flask-WTF + WTForms

### 区块链/网络

- web3.py
- requests / aiohttp / websockets（依赖中已包含）

### 前端

- Jinja2 模板
- 静态资源：`static/css/main.css`、`static/js/main.js`
- 页面模板：`templates/` 下按模块拆分

## 项目结构

```text
Kaspersky-519-WT-05-main/
├─ app.py                    # Flask 应用入口与主要路由
├─ config.py                 # 环境配置（SECRET_KEY、DB、Web3、日志等）
├─ models.py                 # 数据模型（User/HelpRequest/HelpOffer/...）
├─ forms.py                  # 表单定义与校验
├─ extensions.py             # db/login/csrf 扩展实例
├─ blockchain_service.py     # 内部审计链写入与封块逻辑
├─ web3_service.py           # Web3 客户端初始化与获取
├─ watch_blocks.py           # 区块观察工具（internal/core）
├─ init_db.py                # 初始化数据库
├─ create_admin.py           # 创建默认管理员
├─ scripts/
│  └─ migrate_sqlite.py      # SQLite 增量迁移脚本
├─ templates/                # 页面模板（auth/features/admin/profile/...）
├─ static/                   # 静态资源
├─ requirements.txt          # 完整依赖（锁定版本）
└─ requirements.app.txt      # 应用关键依赖（运行建议安装）
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

推荐先安装完整依赖，再补充应用关键依赖：

```bat
pip install -r requirements.txt
pip install -r requirements.app.txt
```

### 4) 初始化数据库（可选）

应用首次运行会自动 `create_all()`，也可手动执行：

```bat
python init_db.py
```

### 5) 启动应用

```bat
python app.py
```

启动后访问：`http://127.0.0.1:5000`

也可使用仓库脚本：

```bat
run_app.bat
```

## 配置说明

通过环境变量覆盖默认配置（`config.py`）：

| 变量名 | 默认值 | 说明 |
|---|---|---|
| `SECRET_KEY` | `change-this-in-production` | Flask 会话与安全密钥 |
| `DATABASE_URL` | `sqlite:///app.db` | SQLAlchemy 连接串 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `ETH_RPC_URL` | 空 | Web3 RPC 地址（可选） |
| `ETH_CHAIN_NAME` | 空 | 链名称（展示用途） |
| `BLOCK_SIZE` | `10` | 内部审计链封块阈值 |

PowerShell 示例：

```powershell
$env:SECRET_KEY="replace-with-a-strong-secret"
$env:DATABASE_URL="sqlite:///app.db"
$env:ETH_RPC_URL=""
$env:BLOCK_SIZE="10"
python app.py
```

## 运行与使用示例

### 常用页面入口

- `/signup`：注册
- `/login`：登录
- `/dashboard`：用户仪表盘
- `/request-help`：发布求助
- `/marketplace`：任务市场
- `/volunteer`：志愿专区
- `/nearby`：附近用户（需个人资料有经纬度）
- `/ngos`：公益组织列表
- `/my-offers`：我的帮助提议
- `/settings/profile`：编辑个人资料
- `/admin`：管理后台（管理员）
- `/blockchain/blocks`：内部区块浏览
- `/web3`：Web3 连接状态

### 典型使用流程

1. 普通用户注册并登录  
2. 在“个人资料”补充经纬度和技能  
3. 发布一条求助（或去市场中给他人提议）  
4. 求助方接受提议并完成任务  
5. 双方提交评价，信誉分自动更新  
6. 管理员在后台处理审核与治理

### 区块观察（内部审计链）

```bat
python watch_blocks.py --source internal --interval 2
```

`run_block1.bat` 会执行同类观察流程。

### SQLite 增量迁移

```bat
python scripts\migrate_sqlite.py
```

## 开发指南

### 本地开发建议

- 使用应用工厂：`from app import create_app`
- 变更模型后：
  - 开发阶段可重建数据库，或
  - 使用 `scripts/migrate_sqlite.py` 做增量列迁移
- 管理员初始化：

```bat
python create_admin.py
```

默认管理员（脚本生成）：

- 用户名：`admin`
- 邮箱：`admin@dailyhelper.com`
- 密码：`admin123`（首次登录后请立即修改）

### 代码组织约定

- 路由与业务：`app.py`
- 数据结构：`models.py`
- 输入校验：`forms.py`
- 链接服务：`blockchain_service.py`、`web3_service.py`
- 页面模板：`templates/` 按模块拆分

### 质量校验现状

当前仓库未提供统一的自动化测试、lint、typecheck 命令配置（未发现 `pytest`/`ruff`/`mypy`/`tox` 等项目级配置）。  
建议后续补充：

- 单元测试（pytest）
- 静态检查（ruff/flake8）
- 类型检查（mypy/pyright）

## 贡献规范

欢迎贡献代码与改进建议，建议遵循以下流程：

1. Fork 并新建功能分支（`feat/*`、`fix/*`）
2. 保持提交粒度清晰，提交信息说明“改动内容 + 原因”
3. 涉及模型/路由/模板改动时同步更新本文档
4. 提交 PR 时附上：
   - 变更摘要
   - 关键截图（如涉及页面）
   - 影响范围与回归点

## 常见问题

### 登录/注册时报错：`Install 'email_validator' for email validation support`

原因：WTForms 的 `Email()` 校验器依赖 `email_validator`。  
解决：

```bat
pip install email-validator
```

或执行：

```bat
pip install -r requirements.app.txt
```

### 附近的人页面没有结果

- 确认当前用户已在个人资料填写 `latitude`/`longitude`
- 确认筛选半径、最低信誉分与技能关键词是否过严

## 许可证

本项目采用仓库中的 `LICENSE` 文件约定。  
如需商用或二次分发，请先确认许可证条款。
