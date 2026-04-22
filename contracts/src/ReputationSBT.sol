// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";

/**
 * @title ReputationSBT — 灵魂绑定信誉代币
 * @notice 不可转让的 ERC-721 代币，代表用户的链上信誉身份证明。
 *         采用 Merkle Tree 机制：
 *           1. 管理员 (Owner) 定期在后端计算所有合格用户的 (address, score) Merkle Root 并上链。
 *           2. 用户凭借后端提供的 Merkle Proof 免费 Mint 或升级 SBT。
 *
 * @dev SBT 等级划分：
 *        - Bronze (铜牌)  : reputation >= 20
 *        - Silver (银牌)  : reputation >= 50
 *        - Gold   (金牌)  : reputation >= 80
 *
 *      Transfer 被禁止（灵魂绑定）——重写 _update 拒绝除 Mint/Burn 之外的转移。
 */
contract ReputationSBT is ERC721, Ownable {

    // ─── 枚举与结构体 ────────────────────────────────────────

    enum Tier { None, Bronze, Silver, Gold }

    struct SBTData {
        Tier   tier;
        uint64 score;        // 链上记录的信誉分快照
        uint64 mintedAt;     // 首次 Mint 时间
        uint64 updatedAt;    // 最近一次升级时间
    }

    // ─── 状态变量 ────────────────────────────────────────────

    /// @notice 当前有效的 Merkle Root，由管理员通过 updateMerkleRoot 设置。
    bytes32 public merkleRoot;

    /// @notice 自增 TokenId 计数器
    uint256 private _nextTokenId;

    /// @notice address => tokenId (每个地址最多一个 SBT)
    mapping(address => uint256) public sbtOf;

    /// @notice tokenId => SBTData
    mapping(uint256 => SBTData) public sbtData;

    /// @notice 等级阈值（可由 Owner 调整）
    uint64 public bronzeThreshold = 20;
    uint64 public silverThreshold = 50;
    uint64 public goldThreshold   = 80;

    // ─── 事件 ────────────────────────────────────────────────

    event MerkleRootUpdated(bytes32 indexed newRoot, uint256 timestamp);
    event SBTMinted(address indexed to, uint256 indexed tokenId, Tier tier, uint64 score);
    event SBTUpgraded(address indexed holder, uint256 indexed tokenId, Tier oldTier, Tier newTier, uint64 newScore);
    event ThresholdsUpdated(uint64 bronze, uint64 silver, uint64 gold);

    // ─── 构造函数 ────────────────────────────────────────────

    constructor()
        ERC721("DailyHelper Reputation SBT", "DHSBT")
        Ownable(msg.sender)
    {
        _nextTokenId = 1; // tokenId 从 1 开始
    }

    // ═════════════════════════════════════════════════════════
    //  管理员函数 (Owner Only)
    // ═════════════════════════════════════════════════════════

    /**
     * @notice 管理员上传新的 Merkle Root。
     * @dev 后端通过 merkle_service.py 计算所有合格用户 (address, score) 的 Merkle Tree，
     *      取 root 后调用此函数。leaf = keccak256(abi.encodePacked(address, uint64(score)))
     */
    function updateMerkleRoot(bytes32 _newRoot) external onlyOwner {
        require(_newRoot != bytes32(0), "SBT: root cannot be zero");
        merkleRoot = _newRoot;
        emit MerkleRootUpdated(_newRoot, block.timestamp);
    }

    /**
     * @notice 管理员可调整等级阈值。
     */
    function setThresholds(uint64 _bronze, uint64 _silver, uint64 _gold) external onlyOwner {
        require(_bronze < _silver && _silver < _gold, "SBT: thresholds must be ascending");
        bronzeThreshold = _bronze;
        silverThreshold = _silver;
        goldThreshold   = _gold;
        emit ThresholdsUpdated(_bronze, _silver, _gold);
    }

    // ═════════════════════════════════════════════════════════
    //  用户函数 — Mint / 升级
    // ═════════════════════════════════════════════════════════

    /**
     * @notice 用户凭 Merkle Proof 免费 Mint 或升级 SBT。
     * @param score  后端确认的信誉分
     * @param proof  Merkle Proof 数组
     *
     * @dev 流程：
     *   1. 验证 leaf = keccak256(abi.encodePacked(msg.sender, score)) 在 merkleRoot 下有效
     *   2. 若用户尚无 SBT → Mint 新代币
     *   3. 若用户已有 SBT → 检查新等级是否高于旧等级，若是则升级
     */
    function mintOrUpgradeSBT(uint64 score, bytes32[] calldata proof) external {
        // ── 1. Merkle 验证 ──
        bytes32 leaf = keccak256(abi.encodePacked(msg.sender, score));
        require(MerkleProof.verify(proof, merkleRoot, leaf), "SBT: invalid Merkle proof");

        Tier newTier = _tierFromScore(score);
        require(newTier != Tier.None, "SBT: score below minimum threshold");

        uint256 existingTokenId = sbtOf[msg.sender];

        if (existingTokenId == 0) {
            // ── 2. 首次 Mint ──
            uint256 tokenId = _nextTokenId++;
            _safeMint(msg.sender, tokenId);

            sbtOf[msg.sender] = tokenId;
            sbtData[tokenId] = SBTData({
                tier:      newTier,
                score:     score,
                mintedAt:  uint64(block.timestamp),
                updatedAt: uint64(block.timestamp)
            });

            emit SBTMinted(msg.sender, tokenId, newTier, score);
        } else {
            // ── 3. 升级已有 SBT ──
            SBTData storage data = sbtData[existingTokenId];
            require(newTier > data.tier, "SBT: new tier must be higher than current");

            Tier oldTier = data.tier;
            data.tier      = newTier;
            data.score     = score;
            data.updatedAt = uint64(block.timestamp);

            emit SBTUpgraded(msg.sender, existingTokenId, oldTier, newTier, score);
        }
    }

    // ═════════════════════════════════════════════════════════
    //  查询函数 (View / Pure)
    // ═════════════════════════════════════════════════════════

    /**
     * @notice 查询某地址的 SBT 等级。外部合约（如 TaskEscrow）用此做权限校验。
     */
    function tierOf(address account) external view returns (Tier) {
        uint256 tokenId = sbtOf[account];
        if (tokenId == 0) return Tier.None;
        return sbtData[tokenId].tier;
    }

    /**
     * @notice 查询某地址的完整 SBT 数据。
     */
    function getSBT(address account) external view returns (
        uint256 tokenId,
        Tier    tier,
        uint64  score,
        uint64  mintedAt,
        uint64  updatedAt
    ) {
        tokenId = sbtOf[account];
        if (tokenId != 0) {
            SBTData storage d = sbtData[tokenId];
            tier      = d.tier;
            score     = d.score;
            mintedAt  = d.mintedAt;
            updatedAt = d.updatedAt;
        }
    }

    /**
     * @notice 检查某地址是否持有指定等级以上的 SBT。
     */
    function hasMinTier(address account, Tier minTier) external view returns (bool) {
        uint256 tokenId = sbtOf[account];
        if (tokenId == 0) return false;
        return sbtData[tokenId].tier >= minTier;
    }

    // ═════════════════════════════════════════════════════════
    //  灵魂绑定：禁止转让
    // ═════════════════════════════════════════════════════════

    /**
     * @dev 重写 ERC-721 的 _update 钩子。
     *      只允许 from == address(0) 的 Mint 操作，
     *      禁止一切普通转移（包括 transferFrom、safeTransferFrom）。
     */
    function _update(address to, uint256 tokenId, address auth)
        internal
        override
        returns (address)
    {
        address from = _ownerOf(tokenId);
        // 允许 Mint (from == 0)，禁止其他转移
        if (from != address(0) && to != address(0)) {
            revert("SBT: soul-bound, transfer disabled");
        }
        return super._update(to, tokenId, auth);
    }

    // ─── 内部辅助 ────────────────────────────────────────────

    function _tierFromScore(uint64 score) internal view returns (Tier) {
        if (score >= goldThreshold)   return Tier.Gold;
        if (score >= silverThreshold) return Tier.Silver;
        if (score >= bronzeThreshold) return Tier.Bronze;
        return Tier.None;
    }
}
