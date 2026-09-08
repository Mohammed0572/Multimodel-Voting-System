export function isValidContractAddress(
  address: string | undefined,
): boolean {
  return Boolean(
    address &&
      address !== "0xYOUR_CONTRACT_ADDRESS_HERE" &&
      /^0x[a-fA-F0-9]{40}$/.test(address),
  );
}

export function normalizeChainId(chainId: string | number): number {
  if (typeof chainId === "number") {
    return chainId;
  }

  return chainId.startsWith("0x")
    ? parseInt(chainId, 16)
    : Number(chainId);
}
