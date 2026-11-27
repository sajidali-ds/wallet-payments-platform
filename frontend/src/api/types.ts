// Mirrors the Pydantic response models of the three services. Money is integer paise.

export interface User {
  id: string;
  email: string;
  role: "user" | "admin";
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface Wallet {
  id: string;
  user_id: string;
  currency: string;
  balance: number;
  created_at: string;
}

export interface Balance {
  wallet_id: string;
  currency: string;
  balance: number;
}

export interface Transaction {
  entry_id: number;
  transfer_id: string;
  type: "transfer" | "deposit";
  amount: number; // signed: positive = money in, negative = money out
  balance_after: number;
  counterparty_wallet_id: string;
  created_at: string;
}

export interface Page<T> {
  items: T[];
  next_cursor: number | null;
}

export interface TransferResult {
  transfer_id: string;
  from_wallet_id: string;
  to_wallet_id: string;
  amount: number;
  balance_after: number;
  created_at: string;
}

export interface DepositResult {
  transfer_id: string;
  wallet_id: string;
  amount: number;
  balance_after: number;
  created_at: string;
}

export interface FraudFlag {
  id: string;
  user_id: string;
  rule: string;
  transfer_count: number;
  window_seconds: number;
  triggering_transfer_id: string;
  created_at: string;
}

export interface Notification {
  id: number;
  event_id: string;
  type: string;
  message: string;
  read_at: string | null;
  created_at: string;
}
