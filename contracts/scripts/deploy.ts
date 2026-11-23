import fs from "fs";
import path from "path";
import { ethers, network } from "hardhat";

async function main() {
  const signers = await ethers.getSigners();
  const deployer = signers[0];
  const oracle = signers[1];
  const factory = await ethers.getContractFactory("LoanRelief");
  const contract = await factory.deploy(oracle.address);
  await contract.waitForDeployment();
  const address = await contract.getAddress();
  const artifactPath = path.resolve(
    __dirname,
    "../artifacts/contracts/LoanRelief.sol/LoanRelief.json",
  );
  const artifact = JSON.parse(fs.readFileSync(artifactPath, "utf8"));
  const chain = await ethers.provider.getNetwork();
  const output = {
    address,
    abi: artifact.abi,
    chainId: Number(chain.chainId),
    contract: "LoanRelief",
    network: network.name,
    deployer: deployer.address,
    oracle: oracle.address,
  };
  const destination = path.resolve(__dirname, "../../backend/chain/deployment.json");
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(destination, JSON.stringify(output, null, 2));
  console.log(`LoanRelief deployed at ${address}`);
  console.log(`Oracle ${oracle.address}`);
  console.log(`Wrote ${destination}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
