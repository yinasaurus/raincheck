import { HardhatUserConfig } from "hardhat/config";
import "@nomicfoundation/hardhat-toolbox";

const config: HardhatUserConfig = {
  solidity: "0.8.20",
  gasReporter: {
    enabled: true,
    offline: true,
    noColors: true,
  },
  networks: {
    localhost: {
      url: "http://127.0.0.1:8545",
    },
  },
};

export default config;
