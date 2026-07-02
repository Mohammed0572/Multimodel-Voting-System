import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import Web3 from 'web3';
// @ts-expect-error @truffle/contract does not publish compatible TypeScript declarations.
import TruffleContract from '@truffle/contract';
import votingArtifacts from "../contracts/Voting.json";

declare global {
  interface Window {
    ethereum?: {
      request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
    };
  }
}

interface Web3ContextType {
  web3: Web3 | null;
  account: string | null;
  contract: any | null;
  isLoading: boolean;
  error: string | null;
}

const Web3Context = createContext<Web3ContextType | undefined>(undefined);

export const useWeb3 = () => {
  const context = useContext(Web3Context);
  if (context === undefined) {
    throw new Error('useWeb3 must be used within a Web3Provider');
  }
  return context;
};

export const Web3Provider = ({ children }: { children: ReactNode }) => {
  const [web3, setWeb3] = useState<Web3 | null>(null);
  const [account, setAccount] = useState<string | null>(null);
  const [contract, setContract] = useState<any | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const initWeb3 = async () => {
      try {
        const VOTING_CONTRACT_ADDRESS = import.meta.env.VITE_CONTRACT_ADDRESS;
        if (!window.ethereum) {
          throw new Error('MetaMask is required to sign voting transactions.');
        }

        await window.ethereum.request({ method: 'eth_requestAccounts' });
        const currentWeb3 = new Web3(window.ethereum as any);
        const expectedChainId = Number(import.meta.env.VITE_NETWORK_ID || 11155111);
        const chainId = await currentWeb3.eth.getChainId();
        
        // Ganache by default uses Network ID 5777 but Chain ID 1337
        const isGanache = expectedChainId === 5777 && Number(chainId) === 1337;
        if (Number(chainId) !== expectedChainId && !isGanache) {
          throw new Error(
            `Wrong blockchain network. Expected chain ID ${expectedChainId}, received ${chainId}.`
          );
        }
        
        setWeb3(currentWeb3);
        
        const accounts = await currentWeb3.eth.getAccounts();
        if (!accounts[0]) {
          throw new Error('No MetaMask account is connected.');
        }
        setAccount(accounts[0]);

        const VotingContract = TruffleContract(votingArtifacts);
        VotingContract.setProvider(currentWeb3.currentProvider);
        VotingContract.defaults({ from: accounts[0] });
        
        let instance;
        if (VOTING_CONTRACT_ADDRESS && VOTING_CONTRACT_ADDRESS !== "0xYOUR_CONTRACT_ADDRESS_HERE") {
          instance = await VotingContract.at(VOTING_CONTRACT_ADDRESS);
        } else {
          instance = await VotingContract.deployed();
        }
        
        setContract(instance);
        setIsLoading(false);
      } catch (err: any) {
        console.error("Failed to initialize web3 or contract.", err);
        setError(err.message || String(err));
        setIsLoading(false);
      }
    };
    initWeb3();
  }, []);

  return (
    <Web3Context.Provider value={{ web3, account, contract, isLoading, error }}>
      {children}
    </Web3Context.Provider>
  );
};
