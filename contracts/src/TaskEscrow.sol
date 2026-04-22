// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title IReputationSBT — 最小化接口，用于跨合约校验 SBT 等级
 */
interface IReputationSBT {
    enum Tier { None, Bronze, Silver, Gold }
    function tierOf(address account) external view returns (Tier);
    function hasMinTier(address account, Tier minTier) external view returns (bool);
}

/**
 * @title TaskEscrow — 任务资金托管与 DAO 仲裁合约
 * @notice 实现付费互助任务的全生命周期链上资金管理：
 *
 *   锁定 (Locked)
 *     ↓  求助者接受提议时存入 ETH
 *   释放 (Completed)
 *     ↓  求助者确认完成 → 资金打入帮助者
 *   仲裁 (Disputed)
 *     ↓  任一方发起争议 → 金牌 SBT 持有者投票
 *   已结算 (Resolved)
 *     ↓  票数达阈值 → 自动执行退款或打款
 *
 * @dev 核心设计决策：
 *   - 志愿任务不走此合约，仅付费任务使用。
 *   - 仲裁投票阈值可配置（构造参数），便于测试。
 *   - 跨合约调用 ReputationSBT.hasMinTier 校验仲裁员资格。
 *   - ReentrancyGuard 防重入攻击。
 */
contract TaskEscrow is Ownable, ReentrancyGuard {

    // ─── 枚举 ────────────────────────────────────────────────

    enum EscrowStatus {
        None,       // 不存在
        Locked,     // 资金已锁定
        Completed,  // 求助者确认完成，资金已释放给帮助者
        Disputed,   // 争议中，等待仲裁投票
        Resolved    // 仲裁完成，资金已按投票结果划转
    }

    enum VoteChoice {
        None,
        PayHelper,   // 支持打款给帮助者
        RefundRequester  // 支持退款给求助者
    }

    // ─── 结构体 ───────────────────────────────────────────────

    struct Escrow {
        uint256       taskId;       // 对应后端 HelpRequest.id
        address       requester;    // 求助者地址
        address       helper;       // 帮助者地址
        uint256       amount;       // 托管金额 (wei)
        EscrowStatus  status;
        uint64        createdAt;
        uint64        resolvedAt;
        // 仲裁投票
        uint32        votesForHelper;    // 支持打款给帮助者的票数
        uint32        votesForRequester; // 支持退款给求助者的票数
    }

    // ─── 状态变量 ────────────────────────────────────────────

    /// @notice SBT 合约引用
    IReputationSBT public sbtContract;

    /// @notice 仲裁投票达到此阈值自动执行
    uint32 public voteThreshold;

    /// @notice taskId => Escrow
    mapping(uint256 => Escrow) public escrows;

    /// @notice taskId => voter => VoteChoice （防止重复投票）
    mapping(uint256 => mapping(address => VoteChoice)) public votes;

    /// @notice 平台手续费率（基点，10000 = 100%）。默认 0 = 无手续费。
    uint256 public feeBasisPoints;

    /// @notice 累积手续费余额（可由 Owner 提取）
    uint256 public accumulatedFees;

    // ─── 事件 ────────────────────────────────────────────────

    event EscrowCreated(uint256 indexed taskId, address indexed requester, address indexed helper, uint256 amount);
    event EscrowReleased(uint256 indexed taskId, address indexed helper, uint256 amount);
    event DisputeRaised(uint256 indexed taskId, address indexed raisedBy);
    event VoteCast(uint256 indexed taskId, address indexed voter, VoteChoice choice);
    event DisputeResolved(uint256 indexed taskId, VoteChoice outcome, uint256 payoutAmount);
    event VoteThresholdUpdated(uint32 oldThreshold, uint32 newThreshold);
    event FeeBasisPointsUpdated(uint256 oldFee, uint256 newFee);
    event FeesWithdrawn(address indexed to, uint256 amount);

    // ─── 构造函数 ────────────────────────────────────────────

    /**
     * @param _sbtContract     ReputationSBT 合约地址
     * @param _voteThreshold   仲裁票数阈值（测试时可设 1，生产建议 3）
     */
    constructor(address _sbtContract, uint32 _voteThreshold)
        Ownable(msg.sender)
    {
        require(_sbtContract != address(0), "Escrow: SBT address cannot be zero");
        require(_voteThreshold > 0, "Escrow: threshold must be > 0");
        sbtContract   = IReputationSBT(_sbtContract);
        voteThreshold = _voteThreshold;
    }

    // ═════════════════════════════════════════════════════════
    //  管理员函数
    // ═════════════════════════════════════════════════════════

    function setVoteThreshold(uint32 _newThreshold) external onlyOwner {
        require(_newThreshold > 0, "Escrow: threshold must be > 0");
        emit VoteThresholdUpdated(voteThreshold, _newThreshold);
        voteThreshold = _newThreshold;
    }

    function setFeeBasisPoints(uint256 _newFee) external onlyOwner {
        require(_newFee <= 1000, "Escrow: fee cannot exceed 10%");
        emit FeeBasisPointsUpdated(feeBasisPoints, _newFee);
        feeBasisPoints = _newFee;
    }

    function withdrawFees(address payable _to) external onlyOwner {
        uint256 amount = accumulatedFees;
        require(amount > 0, "Escrow: no fees to withdraw");
        accumulatedFees = 0;
        (bool ok, ) = _to.call{value: amount}("");
        require(ok, "Escrow: fee transfer failed");
        emit FeesWithdrawn(_to, amount);
    }

    function updateSBTContract(address _newSBT) external onlyOwner {
        require(_newSBT != address(0), "Escrow: SBT address cannot be zero");
        sbtContract = IReputationSBT(_newSBT);
    }

    // ═════════════════════════════════════════════════════════
    //  求助者函数
    // ═════════════════════════════════════════════════════════

    /**
     * @notice 求助者接受提议时调用：锁定 ETH 到合约。
     * @param taskId   后端 HelpRequest.id
     * @param helper   帮助者钱包地址
     *
     * @dev msg.value 即为锁定金额，必须 > 0。
     *      同一个 taskId 不可重复创建。
     */
    function createEscrow(uint256 taskId, address helper) external payable nonReentrant {
        require(msg.value > 0, "Escrow: must send ETH");
        require(helper != address(0), "Escrow: helper cannot be zero");
        require(helper != msg.sender, "Escrow: cannot escrow to yourself");
        require(escrows[taskId].status == EscrowStatus.None, "Escrow: already exists for this task");

        escrows[taskId] = Escrow({
            taskId:            taskId,
            requester:         msg.sender,
            helper:            helper,
            amount:            msg.value,
            status:            EscrowStatus.Locked,
            createdAt:         uint64(block.timestamp),
            resolvedAt:        0,
            votesForHelper:    0,
            votesForRequester: 0
        });

        emit EscrowCreated(taskId, msg.sender, helper, msg.value);
    }

    /**
     * @notice 求助者确认任务完成 → 资金释放给帮助者。
     * @param taskId 任务 ID
     */
    function releaseToHelper(uint256 taskId) external nonReentrant {
        Escrow storage e = escrows[taskId];
        require(e.status == EscrowStatus.Locked, "Escrow: not in Locked state");
        require(msg.sender == e.requester, "Escrow: only requester can release");

        e.status     = EscrowStatus.Completed;
        e.resolvedAt = uint64(block.timestamp);

        uint256 payout = _deductFee(e.amount);
        (bool ok, ) = e.helper.call{value: payout}("");
        require(ok, "Escrow: transfer to helper failed");

        emit EscrowReleased(taskId, e.helper, payout);
    }

    // ═════════════════════════════════════════════════════════
    //  争议与仲裁
    // ═════════════════════════════════════════════════════════

    /**
     * @notice 求助者或帮助者发起争议。
     * @dev 只有 Locked 状态的 Escrow 才能发起争议。
     */
    function raiseDispute(uint256 taskId) external {
        Escrow storage e = escrows[taskId];
        require(e.status == EscrowStatus.Locked, "Escrow: not in Locked state");
        require(
            msg.sender == e.requester || msg.sender == e.helper,
            "Escrow: only parties can raise dispute"
        );

        e.status = EscrowStatus.Disputed;
        emit DisputeRaised(taskId, msg.sender);
    }

    /**
     * @notice 金牌 SBT 持有者 (信誉>=80) 对争议任务投票。
     * @param taskId  任务 ID
     * @param choice  投票选项 (PayHelper 或 RefundRequester)
     *
     * @dev 校验：
     *   1. 仲裁员必须持有 Gold SBT (跨合约调用 ReputationSBT.hasMinTier)
     *   2. 仲裁员不能是争议双方
     *   3. 每人每任务只能投一次
     *   4. 票数达到阈值时自动执行划转
     */
    function voteOnDispute(uint256 taskId, VoteChoice choice) external nonReentrant {
        require(
            choice == VoteChoice.PayHelper || choice == VoteChoice.RefundRequester,
            "Escrow: invalid vote choice"
        );

        Escrow storage e = escrows[taskId];
        require(e.status == EscrowStatus.Disputed, "Escrow: not in Disputed state");

        // 跨合约校验：必须持有金牌 SBT
        require(
            sbtContract.hasMinTier(msg.sender, IReputationSBT.Tier.Gold),
            "Escrow: voter must hold Gold SBT"
        );

        // 仲裁员不能是争议当事人
        require(
            msg.sender != e.requester && msg.sender != e.helper,
            "Escrow: parties cannot vote"
        );

        // 防止重复投票
        require(
            votes[taskId][msg.sender] == VoteChoice.None,
            "Escrow: already voted"
        );

        votes[taskId][msg.sender] = choice;

        if (choice == VoteChoice.PayHelper) {
            e.votesForHelper++;
        } else {
            e.votesForRequester++;
        }

        emit VoteCast(taskId, msg.sender, choice);

        // 检查是否达到阈值 → 自动执行
        _tryResolve(taskId);
    }

    // ═════════════════════════════════════════════════════════
    //  查询函数
    // ═════════════════════════════════════════════════════════

    /**
     * @notice 获取 Escrow 完整信息（前端调用）。
     */
    function getEscrow(uint256 taskId) external view returns (
        address   requester,
        address   helper,
        uint256   amount,
        EscrowStatus status,
        uint64    createdAt,
        uint64    resolvedAt,
        uint32    votesForHelper,
        uint32    votesForRequester
    ) {
        Escrow storage e = escrows[taskId];
        return (
            e.requester, e.helper, e.amount, e.status,
            e.createdAt, e.resolvedAt,
            e.votesForHelper, e.votesForRequester
        );
    }

    /**
     * @notice 查询某仲裁员对某任务的投票。
     */
    function getVote(uint256 taskId, address voter) external view returns (VoteChoice) {
        return votes[taskId][voter];
    }

    // ═════════════════════════════════════════════════════════
    //  内部函数
    // ═════════════════════════════════════════════════════════

    /**
     * @dev 检查某一方票数是否达到阈值，若达到则自动划转资金。
     */
    function _tryResolve(uint256 taskId) internal {
        Escrow storage e = escrows[taskId];

        if (e.votesForHelper >= voteThreshold) {
            // 帮助者胜出 → 资金打给帮助者
            e.status     = EscrowStatus.Resolved;
            e.resolvedAt = uint64(block.timestamp);

            uint256 payout = _deductFee(e.amount);
            (bool ok, ) = e.helper.call{value: payout}("");
            require(ok, "Escrow: transfer to helper failed");

            emit DisputeResolved(taskId, VoteChoice.PayHelper, payout);

        } else if (e.votesForRequester >= voteThreshold) {
            // 求助者胜出 → 资金退回求助者
            e.status     = EscrowStatus.Resolved;
            e.resolvedAt = uint64(block.timestamp);

            uint256 payout = _deductFee(e.amount);
            (bool ok, ) = e.requester.call{value: payout}("");
            require(ok, "Escrow: refund to requester failed");

            emit DisputeResolved(taskId, VoteChoice.RefundRequester, payout);
        }
        // 否则继续等待更多投票
    }

    /**
     * @dev 扣除平台手续费（如果设置了的话），返回实际打款金额。
     */
    function _deductFee(uint256 amount) internal returns (uint256 payout) {
        if (feeBasisPoints == 0) {
            return amount;
        }
        uint256 fee = (amount * feeBasisPoints) / 10000;
        accumulatedFees += fee;
        return amount - fee;
    }
}
