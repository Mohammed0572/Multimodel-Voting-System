import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
  ReactNode,
} from "react";
import Web3 from "web3";
// @ts-expect-error @truffle/contract does not publish compatible TypeScript declarations.
import TruffleContract from "@truffle/contract";
import votingArtifacts from "../contracts/Voting.json";
import { API_BASE } from "./AuthContext";

import { isValidContractAddress, normalizeChainId } from "../utils/blockchain";

declare global {
  interface Window {
    ethereum?: {
      request: (args: {
        method: string;
        params?: unknown[];
      }) => Promise<unknown>;
      on?: (event: string, handler: (...args: any[]) => void) => void;
      removeListener?: (
        event: string,
        handler: (...args: any[]) => void,
      ) => void;
    };
  }
}

interface Web3ContextType {
  web3: Web3 | null;
  account: string | null;
  contract: any | null;
  isLoading: boolean;
  error: string | null;
  electionId: string;
  electionName: string;
  connectWallet: () => Promise<string | null>;
  deployElection: (relayerAddress: string, from: string) => Promise<string>;
  refreshElection: () => Promise<void>;
}

const Web3Context = createContext<Web3ContextType | undefined>(undefined);

interface ElectionInfo {
  election_id: string;
  contract_address: string;
  name: string;
}

export const useWeb3 = () => {
  const context = useContext(Web3Context);
  if (context === undefined) {
    throw new Error("useWeb3 must be used within a Web3Provider");
  }
  return context;
};

export async function requireContractOwner(contract: any, account: string) {
  if (!contract || !account) {
    throw new Error("Contract or account is unavailable.");
  }
  const ownerMethod = contract.methods?.owner
    ? contract.methods.owner().call
    : contract.owner;
  const owner =
    typeof ownerMethod === "function"
      ? await ownerMethod()
      : await contract.owner();

  if (owner.toLowerCase() !== account.toLowerCase()) {
    throw new Error("Connected wallet is not the election contract owner.");
  }
}

export const Web3Provider = ({ children }: { children: ReactNode }) => {
  const [web3, setWeb3] = useState<Web3 | null>(null);
  const [account, setAccount] = useState<string | null>(null);
  const [contract, setContract] = useState<any | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [contractAddress, setContractAddress] = useState("");
  const [electionId, setElectionId] = useState("");
  const [electionName, setElectionName] = useState("");
  const electionRequestRef = useRef(0);

  const connectWallet = useCallback(async () => {
    if (!window.ethereum || !web3) {
      setError("MetaMask is required to sign voting transactions.");
      return null;
    }

    try {
      const requestedAccounts = await window.ethereum.request({
        method: "eth_requestAccounts",
      });
      const nextAccount = Array.isArray(requestedAccounts)
        ? String(requestedAccounts[0] || "")
        : "";

      if (!nextAccount) {
        throw new Error("No MetaMask account is connected.");
      }

      setAccount(nextAccount);
      setError(null);
      return nextAccount;
    } catch (err: any) {
      const message =
        err?.code === 4001
          ? "Wallet connection was cancelled."
          : err?.message || "Unable to connect to MetaMask.";
      setError(message);
      return null;
    }
  }, [web3]);

  const refreshElection = useCallback(async () => {
    const requestId = ++electionRequestRef.current;
    const response = await fetch(`${API_BASE}/election`, {
      credentials: "include",
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error("Unable to refresh the active election.");
    }

    const election = (await response.json()) as ElectionInfo;
    if (requestId !== electionRequestRef.current) return;
    if (
      election.contract_address &&
      !isValidContractAddress(election.contract_address)
    ) {
      throw new Error("The backend returned an invalid election contract address.");
    }

    setElectionId(String(election.election_id || "").toLowerCase());
    setElectionName(String(election.name || ""));
    if (
      web3 &&
      election.contract_address &&
      election.contract_address.toLowerCase() !== contractAddress.toLowerCase()
    ) {
      const VotingContract = TruffleContract(votingArtifacts);
      VotingContract.setProvider(web3.currentProvider);
      if (account) VotingContract.defaults({ from: account });
      const activeContract = await VotingContract.at(
        election.contract_address,
      );
      if (requestId !== electionRequestRef.current) return;
      setContract(activeContract);
      setContractAddress(election.contract_address);
      setError(null);
    }
  }, [account, contractAddress, web3]);

  const deployElection = useCallback(
    async (relayerAddress: string, from: string) => {
      if (!web3) throw new Error("The blockchain network is not connected.");
      const VotingContract = TruffleContract(votingArtifacts);
      VotingContract.setProvider(web3.currentProvider);
      const deployedContract = await VotingContract.new(relayerAddress, {
        from,
      });
      const address = String(
        deployedContract.address || deployedContract.options?.address || "",
      );
      if (!isValidContractAddress(address)) {
        throw new Error("MetaMask deployed the election contract without a valid address.");
      }
      return address;
    },
    [web3],
  );

  useEffect(() => {
    let cancelled = false;

    const initWeb3 = async () => {
      try {
        const configuredAddress = import.meta.env.VITE_CONTRACT_ADDRESS;
        if (!window.ethereum) {
          throw new Error(
            "MetaMask is required to connect to the voting network.",
          );
        }

        const currentWeb3 = new Web3(window.ethereum as any);
        const expectedChainId = normalizeChainId(
          import.meta.env.VITE_NETWORK_ID ||
            import.meta.env.VITE_CHAIN_ID ||
            1337,
        );
        const rawChainId = await currentWeb3.eth.getChainId();
        const chainId = normalizeChainId(rawChainId);
        const isGanache =
          (expectedChainId === 5777 || expectedChainId === 1337) &&
          (chainId === 1337 || chainId === 5777);
        if (chainId !== expectedChainId && !isGanache) {
          throw new Error(
            `Wrong blockchain network. Expected chain ID ${expectedChainId}, received ${chainId}.`,
          );
        }

        const accounts = await currentWeb3.eth.getAccounts();
        const VotingContract = TruffleContract(votingArtifacts);
        VotingContract.setProvider(currentWeb3.currentProvider);
        if (accounts[0]) {
          VotingContract.defaults({ from: accounts[0] });
        }

        let instance: any = null;
        if (isValidContractAddress(configuredAddress)) {
          instance = await VotingContract.at(configuredAddress);
        } else {
          const networkId = await currentWeb3.eth.net.getId();
          const deployedNetworks = votingArtifacts.networks as Record<
            string,
            { address?: string }
          >;
          const deployedNetwork = deployedNetworks?.[String(networkId)];
          if (
            deployedNetwork &&
            isValidContractAddress(deployedNetwork.address)
          ) {
            instance = await VotingContract.at(deployedNetwork.address);
          } else {
            try {
              instance = await VotingContract.deployed();
            } catch {
              throw new Error(
                `Voting contract is not deployed on network ${networkId}.`,
              );
            }
          }
        }

        if (!cancelled) {
          setWeb3(currentWeb3);
          setAccount(accounts[0] || null);
          setContract(instance);
          setContractAddress(
            String(instance?.address || instance?.options?.address || ""),
          );
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
    ethereum?.on?.("accountsChanged", handleAccountsChanged);
    ethereum?.on?.("chainChanged", handleChainChanged);

    return () => {
      cancelled = true;
      ethereum?.removeListener?.("accountsChanged", handleAccountsChanged);
      ethereum?.removeListener?.("chainChanged", handleChainChanged);
    };
  }, []);

  useEffect(() => {
    if (!web3) return;
    let active = true;
    const refresh = () => {
      void refreshElection().catch((refreshError) => {
        if (active) {
          console.error("Failed to refresh the active election.", refreshError);
          setError(
            refreshError instanceof Error
              ? refreshError.message
              : "Unable to refresh the active election.",
          );
        }
      });
    };
    const intervalId = window.setInterval(refresh, 5_000);
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    document.addEventListener("visibilitychange", refreshWhenVisible);
    window.addEventListener("focus", refreshWhenVisible);
    refresh();
    return () => {
      active = false;
      window.clearInterval(intervalId);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      window.removeEventListener("focus", refreshWhenVisible);
    };
  }, [refreshElection, web3]);

  return (
    <Web3Context.Provider
      value={{
        web3,
        account,
        contract,
        isLoading,
        error,
        electionId,
        electionName,
        connectWallet,
        deployElection,
        refreshElection,
      }}
    >
      {children}
    </Web3Context.Provider>
  );
};

export default Web3Context;
