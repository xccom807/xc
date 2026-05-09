---
name: evidence-arbitration-remaining-issues
description: 证据系统与仲裁改进后剩余待修复问题（2026-05-09 审查）
type: project
---

# 证据 & 仲裁系统 — 剩余待修复问题

**审查日期**: 2026-05-09

## Bug 级（应立即修）

1. **文件上传无大小限制** — `config.py` 加 `MAX_CONTENT_LENGTH = 5 * 1024 * 1024`，Flask 默认无限制，用户传大文件会撑爆服务器。
2. **求助者不能提交证据** — `submit_evidence` 端点只允许 `accepted/completed` offer 的帮助者调用。求助者在 disputed 状态下想提交反驳证据会被拒绝。应改为允许任务双方当事人在 `in_progress`/`disputed` 状态下提交。

## March of Nines（迭代改进）

3. **证据与链上脱节** — 合约 `raiseDispute(uint256 taskId)` 不接受 evidence hash。投票者必须完全信任服务器提供的 off-chain 证据。理想做法是合约事件里存 `bytes32 evidenceHash = keccak256(abi.encode(content))`，但需要重新部署合约。
4. **raiseDispute 双通道体验差** — 表单提交和 JS prompt 两条路径并存，用户会 confused。应统一为一条路径。
5. **仲裁无超时机制** — 合约里 Disputed 状态可永久挂起，DAO 投票不到阈值资金永远锁死。需改合约加超时自动退款。
6. **notify_gold_holders 无去重保护** — 同 task_id 短期内多次触发会重复通知金牌用户。加 5 分钟内去重。
