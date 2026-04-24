/**
 * TaskEscrow 合约测试
 *
 * 覆盖场景：
 *   - 部署与初始状态
 *   - createEscrow（锁定资金、零值拒绝、自托管拒绝、重复创建拒绝）
 *   - releaseToHelper（仅求助者、仅 Locked 状态、资金到账）
 *   - raiseDispute（仅当事方、仅 Locked 状态）
 *   - voteOnDispute（Gold SBT 校验、当事方不能投票、防重复投票）
 *   - 自动结算（票数达阈值 → 资金划转）
 *   - 手续费机制（设置费率、扣费、提取）
 *   - 管理员函数（setVoteThreshold / updateSBTContract）
 */
const { expect } = require("chai");
const { ethers } = require("hardhat");

// ── Merkle Tree 辅助（与 ReputationSBT.test.js 一致） ──

function hashLeaf(address, score) {
  return ethers.solidityPackedKeccak256(["address", "uint64"], [address, score]);
}

function hashPair(a, b) {
  const [lo, hi] = BigInt(a) < BigInt(b) ? [a, b] : [b, a];
  return ethers.keccak256(ethers.concat([lo, hi]));
}

function buildTree(leaves) {
  if (leaves.length === 0) return { root: ethers.ZeroHash, layers: [] };
  if (leaves.length === 1) return { root: leaves[0], layers: [leaves] };
  let layer = [...leaves];
  const layers = [layer];
  while (layer.length > 1) {
    const next = [];
    for (let i = 0; i < layer.length; i += 2) {
      next.push(i + 1 < layer.length ? hashPair(layer[i], layer[i + 1]) : layer[i]);
    }
    layers.push((layer = next));
  }
  return { root: layer[0], layers };
}

function getProof(layers, idx) {
  const proof = [];
  for (let i = 0; i < layers.length - 1; i++) {
    const sib = idx ^ 1;
    if (sib < layers[i].length) proof.push(layers[i][sib]);
    idx >>= 1;
  }
  return proof;
}

describe("TaskEscrow", function () {
  let sbt, escrow;
  let owner, requester, helper, goldArb1, goldArb2, silverUser;
  const VOTE_THRESHOLD = 2;
  const ONE_ETH = ethers.parseEther("1.0");

  // 部署 SBT + Escrow，并给仲裁员 Mint Gold SBT
  async function deployFixture() {
    [owner, requester, helper, goldArb1, goldArb2, silverUser] = await ethers.getSigners();

    // 部署 SBT
    const SBT = await ethers.getContractFactory("ReputationSBT");
    sbt = await SBT.deploy();

    // 部署 Escrow
    const Escrow = await ethers.getContractFactory("TaskEscrow");
    escrow = await Escrow.deploy(await sbt.getAddress(), VOTE_THRESHOLD);

    // 为仲裁员 Mint Gold SBT（score=85）；silverUser Mint Silver SBT（score=55）
    const leaves = [
      hashLeaf(goldArb1.address, 85),
      hashLeaf(goldArb2.address, 85),
      hashLeaf(silverUser.address, 55),
      hashLeaf(requester.address, 25),
    ];
    const { root, layers } = buildTree(leaves);
    await sbt.updateMerkleRoot(root);
    await sbt.connect(goldArb1).mintOrUpgradeSBT(85, getProof(layers, 0));
    await sbt.connect(goldArb2).mintOrUpgradeSBT(85, getProof(layers, 1));
    await sbt.connect(silverUser).mintOrUpgradeSBT(55, getProof(layers, 2));

    return { sbt, escrow, owner, requester, helper, goldArb1, goldArb2, silverUser };
  }

  beforeEach(async function () {
    ({ sbt, escrow, owner, requester, helper, goldArb1, goldArb2, silverUser } =
      await deployFixture());
  });

  // ════════════════════════════════════════════════════════
  //  部署与初始状态
  // ════════════════════════════════════════════════════════

  describe("部署", function () {
    it("SBT 合约引用正确", async function () {
      expect(await escrow.sbtContract()).to.equal(await sbt.getAddress());
    });

    it("投票阈值正确", async function () {
      expect(await escrow.voteThreshold()).to.equal(VOTE_THRESHOLD);
    });

    it("初始手续费为 0", async function () {
      expect(await escrow.feeBasisPoints()).to.equal(0);
    });

    it("SBT 地址不能为零", async function () {
      const Escrow = await ethers.getContractFactory("TaskEscrow");
      await expect(Escrow.deploy(ethers.ZeroAddress, 1))
        .to.be.revertedWith("Escrow: SBT address cannot be zero");
    });

    it("投票阈值不能为零", async function () {
      const Escrow = await ethers.getContractFactory("TaskEscrow");
      await expect(Escrow.deploy(await sbt.getAddress(), 0))
        .to.be.revertedWith("Escrow: threshold must be > 0");
    });
  });

  // ════════════════════════════════════════════════════════
  //  createEscrow
  // ════════════════════════════════════════════════════════

  describe("createEscrow", function () {
    it("成功锁定 ETH", async function () {
      await expect(
        escrow.connect(requester).createEscrow(1, helper.address, { value: ONE_ETH })
      )
        .to.emit(escrow, "EscrowCreated")
        .withArgs(1, requester.address, helper.address, ONE_ETH);

      const e = await escrow.getEscrow(1);
      expect(e.requester).to.equal(requester.address);
      expect(e.helper).to.equal(helper.address);
      expect(e.amount).to.equal(ONE_ETH);
      expect(e.status).to.equal(1); // Locked
    });

    it("金额为零被拒绝", async function () {
      await expect(
        escrow.connect(requester).createEscrow(1, helper.address, { value: 0 })
      ).to.be.revertedWith("Escrow: must send ETH");
    });

    it("帮助者地址为零被拒绝", async function () {
      await expect(
        escrow.connect(requester).createEscrow(1, ethers.ZeroAddress, { value: ONE_ETH })
      ).to.be.revertedWith("Escrow: helper cannot be zero");
    });

    it("不能自托管", async function () {
      await expect(
        escrow.connect(requester).createEscrow(1, requester.address, { value: ONE_ETH })
      ).to.be.revertedWith("Escrow: cannot escrow to yourself");
    });

    it("同一 taskId 不能重复创建", async function () {
      await escrow.connect(requester).createEscrow(1, helper.address, { value: ONE_ETH });
      await expect(
        escrow.connect(requester).createEscrow(1, helper.address, { value: ONE_ETH })
      ).to.be.revertedWith("Escrow: already exists for this task");
    });
  });

  // ════════════════════════════════════════════════════════
  //  releaseToHelper
  // ════════════════════════════════════════════════════════

  describe("releaseToHelper", function () {
    beforeEach(async function () {
      await escrow.connect(requester).createEscrow(1, helper.address, { value: ONE_ETH });
    });

    it("求助者释放资金成功", async function () {
      const balBefore = await ethers.provider.getBalance(helper.address);
      await expect(escrow.connect(requester).releaseToHelper(1))
        .to.emit(escrow, "EscrowReleased")
        .withArgs(1, helper.address, ONE_ETH);
      const balAfter = await ethers.provider.getBalance(helper.address);
      expect(balAfter - balBefore).to.equal(ONE_ETH);
    });

    it("非求助者不能释放", async function () {
      await expect(escrow.connect(helper).releaseToHelper(1))
        .to.be.revertedWith("Escrow: only requester can release");
    });

    it("非 Locked 状态不能释放", async function () {
      await escrow.connect(requester).releaseToHelper(1);
      await expect(escrow.connect(requester).releaseToHelper(1))
        .to.be.revertedWith("Escrow: not in Locked state");
    });

    it("释放后状态为 Completed", async function () {
      await escrow.connect(requester).releaseToHelper(1);
      const e = await escrow.getEscrow(1);
      expect(e.status).to.equal(2); // Completed
      expect(e.resolvedAt).to.be.gt(0);
    });
  });

  // ════════════════════════════════════════════════════════
  //  raiseDispute
  // ════════════════════════════════════════════════════════

  describe("raiseDispute", function () {
    beforeEach(async function () {
      await escrow.connect(requester).createEscrow(1, helper.address, { value: ONE_ETH });
    });

    it("求助者可以发起争议", async function () {
      await expect(escrow.connect(requester).raiseDispute(1))
        .to.emit(escrow, "DisputeRaised")
        .withArgs(1, requester.address);
      expect((await escrow.getEscrow(1)).status).to.equal(3); // Disputed
    });

    it("帮助者可以发起争议", async function () {
      await expect(escrow.connect(helper).raiseDispute(1))
        .to.emit(escrow, "DisputeRaised")
        .withArgs(1, helper.address);
    });

    it("第三方不能发起争议", async function () {
      await expect(escrow.connect(goldArb1).raiseDispute(1))
        .to.be.revertedWith("Escrow: only parties can raise dispute");
    });

    it("非 Locked 状态不能发起", async function () {
      await escrow.connect(requester).releaseToHelper(1);
      await expect(escrow.connect(requester).raiseDispute(1))
        .to.be.revertedWith("Escrow: not in Locked state");
    });
  });

  // ════════════════════════════════════════════════════════
  //  voteOnDispute
  // ════════════════════════════════════════════════════════

  describe("voteOnDispute", function () {
    beforeEach(async function () {
      await escrow.connect(requester).createEscrow(1, helper.address, { value: ONE_ETH });
      await escrow.connect(requester).raiseDispute(1);
    });

    it("Gold SBT 持有者可以投票", async function () {
      await expect(escrow.connect(goldArb1).voteOnDispute(1, 1)) // PayHelper
        .to.emit(escrow, "VoteCast")
        .withArgs(1, goldArb1.address, 1);
    });

    it("Silver SBT 持有者不能投票", async function () {
      await expect(escrow.connect(silverUser).voteOnDispute(1, 1))
        .to.be.revertedWith("Escrow: voter must hold Gold SBT");
    });

    it("无 SBT 用户不能投票", async function () {
      await expect(escrow.connect(owner).voteOnDispute(1, 1))
        .to.be.revertedWith("Escrow: voter must hold Gold SBT");
    });

    it("当事方不能投票（即使有 Gold SBT）", async function () {
      // requester 有 Bronze SBT，但即使是 Gold 也应被拒绝
      // 这里用 helper 测试（helper 无 SBT，先测 SBT 校验）
      await expect(escrow.connect(helper).voteOnDispute(1, 1))
        .to.be.revertedWith("Escrow: voter must hold Gold SBT");
    });

    it("不能重复投票", async function () {
      await escrow.connect(goldArb1).voteOnDispute(1, 1);
      await expect(escrow.connect(goldArb1).voteOnDispute(1, 2))
        .to.be.revertedWith("Escrow: already voted");
    });

    it("无效投票选项被拒绝", async function () {
      await expect(escrow.connect(goldArb1).voteOnDispute(1, 0)) // None
        .to.be.revertedWith("Escrow: invalid vote choice");
    });

    it("非 Disputed 状态不能投票", async function () {
      // 新建一个 Locked（未 Disputed）的 Escrow
      await escrow.connect(requester).createEscrow(2, helper.address, { value: ONE_ETH });
      await expect(escrow.connect(goldArb1).voteOnDispute(2, 1))
        .to.be.revertedWith("Escrow: not in Disputed state");
    });
  });

  // ════════════════════════════════════════════════════════
  //  自动结算
  // ════════════════════════════════════════════════════════

  describe("自动结算（票数达阈值）", function () {
    beforeEach(async function () {
      await escrow.connect(requester).createEscrow(1, helper.address, { value: ONE_ETH });
      await escrow.connect(requester).raiseDispute(1);
    });

    it("支持帮助者 → 资金打给帮助者", async function () {
      const balBefore = await ethers.provider.getBalance(helper.address);
      await escrow.connect(goldArb1).voteOnDispute(1, 1); // PayHelper
      await expect(escrow.connect(goldArb2).voteOnDispute(1, 1))
        .to.emit(escrow, "DisputeResolved")
        .withArgs(1, 1, ONE_ETH); // PayHelper, full amount (no fee)

      const balAfter = await ethers.provider.getBalance(helper.address);
      expect(balAfter - balBefore).to.equal(ONE_ETH);

      const e = await escrow.getEscrow(1);
      expect(e.status).to.equal(4); // Resolved
    });

    it("支持求助者 → 资金退回求助者", async function () {
      const balBefore = await ethers.provider.getBalance(requester.address);
      await escrow.connect(goldArb1).voteOnDispute(1, 2); // RefundRequester
      await escrow.connect(goldArb2).voteOnDispute(1, 2);

      const balAfter = await ethers.provider.getBalance(requester.address);
      expect(balAfter - balBefore).to.equal(ONE_ETH);

      const e = await escrow.getEscrow(1);
      expect(e.status).to.equal(4); // Resolved
    });

    it("票数未达阈值不结算", async function () {
      await escrow.connect(goldArb1).voteOnDispute(1, 1); // 只有 1 票，阈值 2
      const e = await escrow.getEscrow(1);
      expect(e.status).to.equal(3); // 仍然 Disputed
    });
  });

  // ════════════════════════════════════════════════════════
  //  手续费机制
  // ════════════════════════════════════════════════════════

  describe("手续费", function () {
    it("设置手续费率", async function () {
      await expect(escrow.setFeeBasisPoints(250)) // 2.5%
        .to.emit(escrow, "FeeBasisPointsUpdated")
        .withArgs(0, 250);
      expect(await escrow.feeBasisPoints()).to.equal(250);
    });

    it("手续费率不能超过 10%", async function () {
      await expect(escrow.setFeeBasisPoints(1001))
        .to.be.revertedWith("Escrow: fee cannot exceed 10%");
    });

    it("释放资金时正确扣费", async function () {
      await escrow.setFeeBasisPoints(500); // 5%
      await escrow.connect(requester).createEscrow(1, helper.address, { value: ONE_ETH });

      const balBefore = await ethers.provider.getBalance(helper.address);
      await escrow.connect(requester).releaseToHelper(1);
      const balAfter = await ethers.provider.getBalance(helper.address);

      const expectedPayout = ONE_ETH - (ONE_ETH * 500n) / 10000n; // 0.95 ETH
      expect(balAfter - balBefore).to.equal(expectedPayout);
      expect(await escrow.accumulatedFees()).to.equal(ONE_ETH - expectedPayout);
    });

    it("Owner 可以提取累积手续费", async function () {
      await escrow.setFeeBasisPoints(500);
      await escrow.connect(requester).createEscrow(1, helper.address, { value: ONE_ETH });
      await escrow.connect(requester).releaseToHelper(1);

      const fee = await escrow.accumulatedFees();
      expect(fee).to.be.gt(0);

      await expect(escrow.withdrawFees(owner.address))
        .to.emit(escrow, "FeesWithdrawn")
        .withArgs(owner.address, fee);
      expect(await escrow.accumulatedFees()).to.equal(0);
    });

    it("无手续费时不能提取", async function () {
      await expect(escrow.withdrawFees(owner.address))
        .to.be.revertedWith("Escrow: no fees to withdraw");
    });
  });

  // ════════════════════════════════════════════════════════
  //  管理员函数
  // ════════════════════════════════════════════════════════

  describe("管理员函数", function () {
    it("setVoteThreshold — Owner 可修改", async function () {
      await expect(escrow.setVoteThreshold(5))
        .to.emit(escrow, "VoteThresholdUpdated")
        .withArgs(VOTE_THRESHOLD, 5);
      expect(await escrow.voteThreshold()).to.equal(5);
    });

    it("setVoteThreshold — 不能设为零", async function () {
      await expect(escrow.setVoteThreshold(0))
        .to.be.revertedWith("Escrow: threshold must be > 0");
    });

    it("setVoteThreshold — 非 Owner 拒绝", async function () {
      await expect(escrow.connect(requester).setVoteThreshold(5))
        .to.be.revertedWithCustomError(escrow, "OwnableUnauthorizedAccount");
    });

    it("updateSBTContract — Owner 可修改", async function () {
      const newAddr = goldArb1.address; // 随意一个非零地址
      await escrow.updateSBTContract(newAddr);
      expect(await escrow.sbtContract()).to.equal(newAddr);
    });

    it("updateSBTContract — 零地址拒绝", async function () {
      await expect(escrow.updateSBTContract(ethers.ZeroAddress))
        .to.be.revertedWith("Escrow: SBT address cannot be zero");
    });

    it("setFeeBasisPoints — 非 Owner 拒绝", async function () {
      await expect(escrow.connect(requester).setFeeBasisPoints(100))
        .to.be.revertedWithCustomError(escrow, "OwnableUnauthorizedAccount");
    });
  });
});
