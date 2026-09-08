const Voting = artifacts.require("Voting");

module.exports = async function (deployer, network, accounts) {
  const configuredRelayer = process.env.RELAYER_ADDRESS;

  const relayer =
    configuredRelayer && configuredRelayer.trim().length > 0
      ? configuredRelayer
      : accounts[0];

  if (!/^0x[a-fA-F0-9]{40}$/.test(relayer)) {
    throw new Error(`Invalid relayer address: ${relayer}`);
  }

  await deployer.deploy(Voting, relayer);
};
