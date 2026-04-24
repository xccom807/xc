/**
 * ReputationSBT 合约测试
 *
 * 覆盖场景：
 *   - 部署与初始状态
 *   - Merkle Root 管理（权限、零值校验）
 *   - 等级阈值管理（权限、升序校验）
 *   - Merkle Proof Mint（合法、非法、分数不足）
 *   - SBT 升级（高等级、同/低等级拒绝）
 *   - 灵魂绑定禁止转让
 *   - 查询函数（tierOf / getSBT / hasMinTier）
 */
const { expect } = require("chai");
const { ethers } = require("hardhat");

// ── Merkle Tree 辅助函数（匹配 OpenZeppelin MerkleProof 排序规则） ──

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

describe("ReputationSBT", function () {
  let sbt, owner, alice, bob, charlie;

  // 复用的部署 fixture
  async function deployFixture() {
    [owner, alice, bob, charlie] = await ethers.getSigners();
    const SBT = await ethers.getContractFactory("ReputationSBT");
    sbt = await SBT.deploy();
    return { sbt, owner, alice, bob, charlie };
  }

  beforeEach(async function () {
    ({ sbt, owner, alice, bob, charlie } = await deployFixture());
  });

  // ════════════════════════════════════════════════════════
  //  部署与初始状态
  // ════════════════════════════════════════════════════════

  describe("部署", function () {
    it("名称和符号正确", async function () {
      expect(await sbt.name()).to.equal("DailyHelper Reputation SBT");
      expect(await sbt.symbol()).to.equal("DHSBT");
    });

    it("Owner 是部署者", async function () {
      expect(await sbt.owner()).to.equal(owner.address);
    });

    it("初始 Merkle Root 为零", async function () {
      expect(await sbt.merkleRoot()).to.equal(ethers.ZeroHash);
    });

    it("默认等级阈值: 20 / 50 / 80", async function () {
      expect(await sbt.bronzeThreshold()).to.equal(20);
      expect(await sbt.silverThreshold()).to.equal(50);
      expect(await sbt.goldThreshold()).to.equal(80);
    });
  });

  // ════════════════════════════════════════════════════════
  //  Merkle Root 管理
  // ════════════════════════════════════════════════════════

  describe("updateMerkleRoot", function () {
    it("Owner 可以更新 Merkle Root", async function () {
      const root = ethers.keccak256(ethers.toUtf8Bytes("test"));
      await expect(sbt.updateMerkleRoot(root))
        .to.emit(sbt, "MerkleRootUpdated")
        .withArgs(root, (ts) => ts > 0);
      expect(await sbt.merkleRoot()).to.equal(root);
    });

    it("非 Owner 不能更新", async function () {
      const root = ethers.keccak256(ethers.toUtf8Bytes("test"));
      await expect(sbt.connect(alice).updateMerkleRoot(root))
        .to.be.revertedWithCustomError(sbt, "OwnableUnauthorizedAccount");
    });

    it("零值 Root 被拒绝", async function () {
      await expect(sbt.updateMerkleRoot(ethers.ZeroHash))
        .to.be.revertedWith("SBT: root cannot be zero");
    });
  });

  // ════════════════════════════════════════════════════════
  //  等级阈值管理
  // ════════════════════════════════════════════════════════

  describe("setThresholds", function () {
    it("Owner 可以修改阈值", async function () {
      await expect(sbt.setThresholds(10, 30, 60))
        .to.emit(sbt, "ThresholdsUpdated")
        .withArgs(10, 30, 60);
      expect(await sbt.bronzeThreshold()).to.equal(10);
    });

    it("非升序阈值被拒绝", async function () {
      await expect(sbt.setThresholds(50, 50, 80))
        .to.be.revertedWith("SBT: thresholds must be ascending");
      await expect(sbt.setThresholds(80, 50, 20))
        .to.be.revertedWith("SBT: thresholds must be ascending");
    });

    it("非 Owner 不能修改", async function () {
      await expect(sbt.connect(alice).setThresholds(10, 30, 60))
        .to.be.revertedWithCustomError(sbt, "OwnableUnauthorizedAccount");
    });
  });

  // ════════════════════════════════════════════════════════
  //  Merkle Proof Mint
  // ════════════════════════════════════════════════════════

  describe("mintOrUpgradeSBT — 首次 Mint", function () {
    let root, layers;

    beforeEach(async function () {
      // 构建包含 alice(25=Bronze)、bob(55=Silver)、charlie(85=Gold) 的 Merkle Tree
      const leaves = [
        hashLeaf(alice.address, 25),
        hashLeaf(bob.address, 55),
        hashLeaf(charlie.address, 85),
      ];
      ({ root, layers } = buildTree(leaves));
      await sbt.updateMerkleRoot(root);
    });

    it("合法 Proof — 铜牌 Mint", async function () {
      const proof = getProof(layers, 0);
      await expect(sbt.connect(alice).mintOrUpgradeSBT(25, proof))
        .to.emit(sbt, "SBTMinted")
        .withArgs(alice.address, 1, 1, 25); // tier=1=Bronze
      expect(await sbt.sbtOf(alice.address)).to.equal(1);
    });

    it("合法 Proof — 银牌 Mint", async function () {
      const proof = getProof(layers, 1);
      await expect(sbt.connect(bob).mintOrUpgradeSBT(55, proof))
        .to.emit(sbt, "SBTMinted")
        .withArgs(bob.address, 1, 2, 55); // tier=2=Silver
    });

    it("合法 Proof — 金牌 Mint", async function () {
      const proof = getProof(layers, 2);
      await expect(sbt.connect(charlie).mintOrUpgradeSBT(85, proof))
        .to.emit(sbt, "SBTMinted")
        .withArgs(charlie.address, 1, 3, 85); // tier=3=Gold
    });

    it("非法 Proof 被拒绝", async function () {
      const badProof = getProof(layers, 1); // bob 的 proof
      await expect(sbt.connect(alice).mintOrUpgradeSBT(25, badProof))
        .to.be.revertedWith("SBT: invalid Merkle proof");
    });

    it("错误分数被拒绝", async function () {
      const proof = getProof(layers, 0);
      await expect(sbt.connect(alice).mintOrUpgradeSBT(99, proof))
        .to.be.revertedWith("SBT: invalid Merkle proof");
    });

    it("分数低于最低阈值被拒绝", async function () {
      // 添加一个分数=10 的叶子
      const leaves = [
        hashLeaf(alice.address, 10),
        hashLeaf(bob.address, 55),
      ];
      const { root: r, layers: l } = buildTree(leaves);
      await sbt.updateMerkleRoot(r);
      const proof = getProof(l, 0);
      await expect(sbt.connect(alice).mintOrUpgradeSBT(10, proof))
        .to.be.revertedWith("SBT: score below minimum threshold");
    });
  });

  // ════════════════════════════════════════════════════════
  //  SBT 升级
  // ════════════════════════════════════════════════════════

  describe("mintOrUpgradeSBT — 升级", function () {
    beforeEach(async function () {
      // 先以 Bronze 分数 Mint
      const leaves = [hashLeaf(alice.address, 25), hashLeaf(bob.address, 55)];
      const { root, layers } = buildTree(leaves);
      await sbt.updateMerkleRoot(root);
      const proof = getProof(layers, 0);
      await sbt.connect(alice).mintOrUpgradeSBT(25, proof);
    });

    it("升级到更高等级成功", async function () {
      // 新 Root：alice 升级到 Silver(55)
      const leaves = [hashLeaf(alice.address, 55), hashLeaf(bob.address, 85)];
      const { root, layers } = buildTree(leaves);
      await sbt.updateMerkleRoot(root);
      const proof = getProof(layers, 0);

      await expect(sbt.connect(alice).mintOrUpgradeSBT(55, proof))
        .to.emit(sbt, "SBTUpgraded")
        .withArgs(alice.address, 1, 1, 2, 55); // oldTier=Bronze(1), newTier=Silver(2)
    });

    it("同等级不能升级", async function () {
      // 同为 Bronze 但分数不同
      const leaves = [hashLeaf(alice.address, 30), hashLeaf(bob.address, 55)];
      const { root, layers } = buildTree(leaves);
      await sbt.updateMerkleRoot(root);
      const proof = getProof(layers, 0);

      await expect(sbt.connect(alice).mintOrUpgradeSBT(30, proof))
        .to.be.revertedWith("SBT: new tier must be higher than current");
    });
  });

  // ════════════════════════════════════════════════════════
  //  灵魂绑定：禁止转让
  // ════════════════════════════════════════════════════════

  describe("灵魂绑定", function () {
    beforeEach(async function () {
      const leaves = [hashLeaf(alice.address, 25), hashLeaf(bob.address, 55)];
      const { root, layers } = buildTree(leaves);
      await sbt.updateMerkleRoot(root);
      await sbt.connect(alice).mintOrUpgradeSBT(25, getProof(layers, 0));
    });

    it("transferFrom 被禁止", async function () {
      await expect(
        sbt.connect(alice).transferFrom(alice.address, bob.address, 1)
      ).to.be.revertedWith("SBT: soul-bound, transfer disabled");
    });

    it("safeTransferFrom 被禁止", async function () {
      await expect(
        sbt.connect(alice)["safeTransferFrom(address,address,uint256)"](
          alice.address, bob.address, 1
        )
      ).to.be.revertedWith("SBT: soul-bound, transfer disabled");
    });
  });

  // ════════════════════════════════════════════════════════
  //  查询函数
  // ════════════════════════════════════════════════════════

  describe("查询函数", function () {
    beforeEach(async function () {
      const leaves = [
        hashLeaf(alice.address, 25),
        hashLeaf(bob.address, 55),
        hashLeaf(charlie.address, 85),
      ];
      const { root, layers } = buildTree(leaves);
      await sbt.updateMerkleRoot(root);
      await sbt.connect(alice).mintOrUpgradeSBT(25, getProof(layers, 0));
      await sbt.connect(bob).mintOrUpgradeSBT(55, getProof(layers, 1));
      await sbt.connect(charlie).mintOrUpgradeSBT(85, getProof(layers, 2));
    });

    it("tierOf 返回正确等级", async function () {
      expect(await sbt.tierOf(alice.address)).to.equal(1);   // Bronze
      expect(await sbt.tierOf(bob.address)).to.equal(2);     // Silver
      expect(await sbt.tierOf(charlie.address)).to.equal(3); // Gold
      expect(await sbt.tierOf(owner.address)).to.equal(0);   // None
    });

    it("getSBT 返回完整数据", async function () {
      const data = await sbt.getSBT(alice.address);
      expect(data.tokenId).to.equal(1);
      expect(data.tier).to.equal(1);
      expect(data.score).to.equal(25);
      expect(data.mintedAt).to.be.gt(0);
    });

    it("hasMinTier 正确校验", async function () {
      expect(await sbt.hasMinTier(charlie.address, 3)).to.be.true;  // Gold >= Gold
      expect(await sbt.hasMinTier(charlie.address, 1)).to.be.true;  // Gold >= Bronze
      expect(await sbt.hasMinTier(alice.address, 2)).to.be.false;   // Bronze < Silver
      expect(await sbt.hasMinTier(owner.address, 1)).to.be.false;   // None < Bronze
    });

    it("每个地址最多一个 SBT（tokenId 递增）", async function () {
      expect(await sbt.sbtOf(alice.address)).to.equal(1);
      expect(await sbt.sbtOf(bob.address)).to.equal(2);
      expect(await sbt.sbtOf(charlie.address)).to.equal(3);
    });
  });
});
