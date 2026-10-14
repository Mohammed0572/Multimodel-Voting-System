const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '../.env') });
let testProvider;

module.exports = {
  contracts_directory: path.join(__dirname, "contracts"),
  contracts_build_directory: path.join(__dirname, "../../src/contracts"),
  migrations_directory: path.join(__dirname, "migrations"),
  // See <http://truffleframework.com/docs/advanced/configuration>
  // for more about customizing your Truffle configuration!
  networks: {
    test: {
      provider: () => {
        if (!testProvider) {
          const ganache = require('ganache');
          testProvider = ganache.provider({ logging: { quiet: true } });
        }
        return testProvider;
      },
      network_id: "*"
    },
    development: {
      host: "127.0.0.1",
      port: 7545,
      network_id: "*" // Match any network id
    },
    sepolia: {
      provider: () => {
        const HDWalletProvider = require('@truffle/hdwallet-provider');
        return new HDWalletProvider(
          process.env.MNEMONIC,
          process.env.SEPOLIA_RPC_URL
        );
      },
      network_id: 11155111,
      confirmations: 2,
      timeoutBlocks: 200,
      skipDryRun: true
    }
  },
  compilers: {
    solc: {
      version: "0.8.24",
      settings: {
        evmVersion: "paris"
      }
    }
  }
}
