import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import Web3 from 'web3';
// @ts-expect-error @truffle/contract does not publish compatible TypeScript declarations.
import TruffleContract from '@truffle/contract';
import votingArtifacts from "../contracts/Voting.json";

declare global {
  interface Window {
    ethereum?: {
      request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
      on?: (event: string, handler: (...args: any[]) => void) => void;
      removeListener?: (event: string, handler: (...args: any[]) => void) => void;
    };
  }
}

interface Web3ContextType {
  web3: Web3 | null;
  account: string | null;
  contract: any | null;
  isLoading: boolean;
  error: string | null;
  connectWallet: () => Promise<string | null>;
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

  const connectWallet = useCallback(async () => {
    if (!window.ethereum || !web3) {
      setError('MetaMask is required to sign voting transactions.');
      return null;
    }

    try {
      const requestedAccounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
      const nextAccount = Array.isArray(requestedAccounts)
        ? String(requestedAccounts[0] || '')
        : '';

      if (!nextAccount) {
        throw new Error('No MetaMask account is connected.');
      }

      setAccount(nextAccount);
      if (contract) {
        contract.defaults({ from: nextAccount });
      }
      setError(null);
      return nextAccount;
    } catch (err: any) {
      const message = err?.code === 4001
        ? 'Wallet connection was cancelled.'
        : err?.message || 'Unable to connect to MetaMask.';
      setError(message);
      return null;
    }
  }, [contract, web3]);

  useEffect(() => {
    let cancelled = false;

    const initWeb3 = async () => {
      try {
        const VOTING_CONTRACT_ADDRESS = import.meta.env.VITE_CONTRACT_ADDRESS;
        if (!window.ethereum) {
          throw new Error('MetaMask is required to connect to the voting network.');
        }

        // Read existing permissions silently. A wallet popup should only appear
        // when a protected flow explicitly calls connectWallet().
        const currentWeb3 = new Web3(window.ethereum as any);
        const expectedChainId = Number(import.meta.env.VITE_NETWORK_ID || 11155111);
        const chainId = await currentWeb3.eth.getChainId();
        const isGanache = expectedChainId === 5777 && Number(chainId) === 1337;
        if (Number(chainId) !== expectedChainId && !isGanache) {
          throw new Error(
            `Wrong blockchain network. Expected chain ID ${expectedChainId}, received ${chainId}.`
          );
        }

        const accounts = await currentWeb3.eth.getAccounts();
        const VotingContract = TruffleContract(votingArtifacts);
        VotingContract.setProvider(currentWeb3.currentProvider);
        if (accounts[0]) {
          VotingContract.defaults({ from: accounts[0] });
        }

        const instance = VOTING_CONTRACT_ADDRESS && VOTING_CONTRACT_ADDRESS !== "0xYOUR_CONTRACT_ADDRESS_HERE"
          ? await VotingContract.at(VOTING_CONTRACT_ADDRESS)
          : await VotingContract.deployed();

        if (!cancelled) {
          setWeb3(currentWeb3);
          setAccount(accounts[0] || null);
          setContract(instance);
          setIsLoading(false);
        }
      } catch (err: any) {
        if (!cancelled) {
          console.error("Failed to initialize web3 or contract.", err);
          setError(err.message || String(err));
          setIsLoading(false);
        }
      }
    };

    initWeb3();

    const handleAccountsChanged = (accounts: string[]) => {
      setAccount(accounts[0] || null);
    };

    const handleChainChanged = () => {
      window.location.reload();
    };

    const ethereum = window.ethereum;
    ethereum?.on?.('accountsChanged', handleAccountsChanged);
    ethereum?.on?.('chainChanged', handleChainChanged);

    return () => {
      cancelled = true;
      ethereum?.removeListener?.('accountsChanged', handleAccountsChanged);
      ethereum?.removeListener?.('chainChanged', handleChainChanged);
    };
  }, []);

  return (
    <Web3Context.Provider value={{ web3, account, contract, isLoading, error, connectWallet }}>
      {children}
    </Web3Context.Provider>
  );
};

export default Web3Context;
