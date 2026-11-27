import type {
  Balance,
  DepositResult,
  FraudFlag,
  Notification,
  Page,
  TokenResponse,
  Transaction,
  TransferResult,
  User,
  Wallet,
} from "./types";

// Every service answers errors as {"error": {"code", "message"}}. FastAPI's own validation errors
// (422) use {"detail": [...]} instead; both are turned into one ApiError here so the UI never has
// to care. status 0 means the request never got an answer (offline, gateway down).
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfterSeconds: number | null;

  constructor(status: number, code: string, message: string, retryAfterSeconds: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

interface Session {
  getToken: () => string | null;
  onUnauthorized: () => void;
}

let session: Session = { getToken: () => null, onUnauthorized: () => {} };

export function configureApi(next: Session): void {
  session = next;
}

interface RequestOptions {
  body?: unknown;
  headers?: Record<string, string>;
  authenticated?: boolean;
}

interface ApiResponse<T> {
  data: T;
  headers: Headers;
}

function describeValidationError(detail: unknown): string {
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: unknown; loc?: unknown };
    const message = typeof first.msg === "string" ? first.msg.replace(/^Value error, /, "") : "";
    const field = Array.isArray(first.loc) ? String(first.loc[first.loc.length - 1]) : "";
    if (message) return field && field !== "body" ? `${field}: ${message}` : message;
  }
  return "The request was not valid.";
}

async function toApiError(response: Response): Promise<ApiError> {
  const retryHeader = response.headers.get("Retry-After");
  const retryAfter = retryHeader && /^\d+$/.test(retryHeader) ? Number(retryHeader) : null;
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    // not JSON (for example an HTML error page from a proxy)
  }
  const body = (payload ?? {}) as { error?: { code?: string; message?: string }; detail?: unknown };
  if (body.error && typeof body.error.message === "string") {
    return new ApiError(response.status, body.error.code ?? "error", body.error.message, retryAfter);
  }
  if (body.detail !== undefined) {
    return new ApiError(response.status, "validation_error", describeValidationError(body.detail), retryAfter);
  }
  const fallback = response.status >= 500 ? "The server had a problem. Try again in a moment." : "The request failed.";
  return new ApiError(response.status, "http_error", fallback, retryAfter);
}

async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<ApiResponse<T>> {
  const { body, headers = {}, authenticated = true } = options;
  const finalHeaders: Record<string, string> = { Accept: "application/json", ...headers };
  if (body !== undefined) finalHeaders["Content-Type"] = "application/json";
  if (authenticated) {
    const token = session.getToken();
    if (token) finalHeaders.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers: finalHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the server. Check your connection and try again.");
  }

  if (!response.ok) {
    const error = await toApiError(response);
    if (response.status === 401 && authenticated) session.onUnauthorized();
    throw error;
  }
  return { data: (await response.json()) as T, headers: response.headers };
}

// ---- auth -------------------------------------------------------------------------------------

export async function register(email: string, password: string): Promise<User> {
  return (await request<User>("POST", "/auth/register", { body: { email, password }, authenticated: false })).data;
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  return (await request<TokenResponse>("POST", "/auth/login", { body: { email, password }, authenticated: false }))
    .data;
}

export async function getMe(): Promise<User> {
  return (await request<User>("GET", "/auth/me")).data;
}

// ---- wallets ----------------------------------------------------------------------------------

export async function getMyWallet(): Promise<Wallet> {
  return (await request<Wallet>("GET", "/wallets/me")).data;
}

export async function createWallet(): Promise<Wallet> {
  return (await request<Wallet>("POST", "/wallets")).data;
}

export async function getMyBalance(): Promise<Balance> {
  return (await request<Balance>("GET", "/wallets/me/balance")).data;
}

export async function listTransactions(limit = 20, cursor: number | null = null): Promise<Page<Transaction>> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (cursor !== null) query.set("cursor", String(cursor));
  return (await request<Page<Transaction>>("GET", `/wallets/me/transactions?${query}`)).data;
}

// ---- transfers --------------------------------------------------------------------------------

export interface TransferOutcome {
  transfer: TransferResult;
  replayed: boolean; // true when the server answered from its stored response (same key sent twice)
}

export async function createTransfer(
  toWalletId: string,
  amountPaise: number,
  idempotencyKey: string,
): Promise<TransferOutcome> {
  const { data, headers } = await request<TransferResult>("POST", "/transfers", {
    body: { to_wallet_id: toWalletId, amount: amountPaise },
    headers: { "Idempotency-Key": idempotencyKey },
  });
  return { transfer: data, replayed: headers.get("Idempotent-Replay") === "true" };
}

// ---- admin ------------------------------------------------------------------------------------

export async function depositToWallet(walletId: string, amountPaise: number): Promise<DepositResult> {
  return (
    await request<DepositResult>("POST", `/wallets/${encodeURIComponent(walletId)}/deposit`, {
      body: { amount: amountPaise },
    })
  ).data;
}

export async function listFraudFlags(limit = 50): Promise<FraudFlag[]> {
  return (await request<FraudFlag[]>("GET", `/admin/fraud-flags?limit=${limit}`)).data;
}

// ---- notifications ----------------------------------------------------------------------------

export async function listNotifications(limit = 20, cursor: number | null = null): Promise<Page<Notification>> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (cursor !== null) query.set("cursor", String(cursor));
  return (await request<Page<Notification>>("GET", `/notifications?${query}`)).data;
}
