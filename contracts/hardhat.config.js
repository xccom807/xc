require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config({ path: "../.env" });

// 仅在部署到 Sepolia 时需要真实私钥，本地测试使用 Hardhat 内置账号
const PRIVATE_KEY = process.env.ETH_SIGNER_PRIVATE_KEY || "0000000000000000000000000000000000000000000000000000000000000001";

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: "0.8.24",
    settings: {
      evmVersion: "cancun",
      optimizer: {
        enabled: true,
        runs: 200,
      },
    },
  },
  paths: {
    sources: "./src",
    cache: "./cache",
    artifacts: "./artifacts",
  },
  networks: {
    sepolia: {
      url: process.env.ETH_RPC_URL || "",
      accounts: [`0x${PRIVATE_KEY}`],
    },
  },
};
