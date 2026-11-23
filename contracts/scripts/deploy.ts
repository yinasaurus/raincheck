import { ethers, artifacts, network } from "hardhat";
import * as fs from "fs";
import * as path from "path";

// Deploys LoanRelief to the selected network and writes ../backend/chain/deployment.json
// so the Python backend can load the address + ABI.
// Local default: the Hardhat node's account #1 acts as the oracle (local test key only).
async function main() {
  const signers = await ethers.getSigners();
  const deployer = signers[0];
  const oracle = process.env.ORACLE_ADDRESS ?? signers[1].address;

  const Factory = await ethers.getContractFactory("LoanRelief");
  const contract = await Factory.deploy(oracle);
  await contract.waitForDeployment();
  const address = await contract.getAddress();

  const artifact = await artifacts.readArtifact("LoanRelief");
  const out = {
    network: network.name,
    chainId: Number((await ethers.provider.getNetwork()).chainId),
    address,
    deployer: deployer.address,
    oracle,
    abi: artifact.abi,
    deployedAt: new Date().toISOString(),
  };

  const outPath = path.resolve(__dirname, "../../backend/chain/deployment.json");
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, JSON.stringify(out, null, 2));
  console.log(`LoanRelief deployed to ${address} on ${network.name} (oracle ${oracle})`);
  console.log(`Wrote ${outPath}`);
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
