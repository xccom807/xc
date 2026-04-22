/**
 * DailyHelper 合约部署脚本
 *
 * 部署顺序：
 *   1. ReputationSBT（无依赖）
 *   2. TaskEscrow（依赖 SBT 地址 + 投票阈值）
 *
 * 用法：
 *   npx hardhat run scripts/deploy.js --network sepolia
 */
const { ethers } = require("hardhat");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("Deploying with account:", deployer.address);
  console.log("Balance:", ethers.formatEther(await ethers.provider.getBalance(deployer.address)), "ETH");

  // ── 1. 部署 ReputationSBT ──
  console.log("\n--- Deploying ReputationSBT ---");
  const SBT = await ethers.getContractFactory("ReputationSBT");
  const sbt = await SBT.deploy();
  await sbt.waitForDeployment();
  const sbtAddress = await sbt.getAddress();
  console.log("ReputationSBT deployed at:", sbtAddress);

  // ── 2. 部署 TaskEscrow ──
  // 投票阈值：测试环境设为 1，生产环境建议 3
  const VOTE_THRESHOLD = 1;
  console.log("\n--- Deploying TaskEscrow ---");
  console.log("  SBT address:", sbtAddress);
  console.log("  Vote threshold:", VOTE_THRESHOLD);

  const Escrow = await ethers.getContractFactory("TaskEscrow");
  const escrow = await Escrow.deploy(sbtAddress, VOTE_THRESHOLD);
  await escrow.waitForDeployment();
  const escrowAddress = await escrow.getAddress();
  console.log("TaskEscrow deployed at:", escrowAddress);

  // ── 输出配置 ──
  console.log("\n========================================");
  console.log("Deployment complete! Add to config.py or .env:");
  console.log(`  SBT_CONTRACT_ADDRESS=${sbtAddress}`);
  console.log(`  ESCROW_CONTRACT_ADDRESS=${escrowAddress}`);
  console.log("========================================");
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
