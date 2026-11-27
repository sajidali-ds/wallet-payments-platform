import { afterEach, describe, expect, it } from "vitest";
import { ApiError, configureApi, createTransfer, getMyWallet } from "./client";

type FetchCall = { path: string; init: RequestInit };

const realFetch = globalThis.fetch;

function stubFetch(respond: (call: FetchCall) => Response | Promise<Response>): FetchCall[] {
  const calls: FetchCall[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const call = { path: String(input), init: init ?? {} };
    calls.push(call);
    return respond(call);
  }) as typeof fetch;
  return calls;
}

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

async function failureOf(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error("expected the request to fail");
}

afterEach(() => {
  globalThis.fetch = realFetch;
  configureApi({ getToken: () => null, onUnauthorized: () => {} });
});

describe("api client", () => {
  it("sends the bearer token and the Idempotency-Key header", async () => {
    configureApi({ getToken: () => "tok123", onUnauthorized: () => {} });
    const calls = stubFetch(() =>
      json({ transfer_id: "t", from_wallet_id: "a", to_wallet_id: "b", amount: 100, balance_after: 900, created_at: "x" }, 201),
    );
    await createTransfer("b", 100, "key-1");
    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer tok123");
    expect(headers["Idempotency-Key"]).toBe("key-1");
    expect(calls[0].init.body).toBe(JSON.stringify({ to_wallet_id: "b", amount: 100 }));
  });

  it("reports when the server replayed a stored response", async () => {
    stubFetch(() => json({ amount: 100, balance_after: 900 }, 201, { "Idempotent-Replay": "true" }));
    const outcome = await createTransfer("b", 100, "key-1");
    expect(outcome.replayed).toBe(true);
  });

  it("turns the services' error shape into an ApiError", async () => {
    stubFetch(() => json({ error: { code: "insufficient_funds", message: "Insufficient funds" } }, 422));
    const error = await failureOf(createTransfer("b", 100, "k"));
    expect(error.status).toBe(422);
    expect(error.code).toBe("insufficient_funds");
    expect(error.message).toBe("Insufficient funds");
  });

  it("turns FastAPI validation errors into one readable message", async () => {
    stubFetch(() => json({ detail: [{ loc: ["body", "amount"], msg: "Input should be greater than 0" }] }, 422));
    const error = await failureOf(createTransfer("b", 0, "k"));
    expect(error.code).toBe("validation_error");
    expect(error.message).toBe("amount: Input should be greater than 0");
  });

  it("reads Retry-After on rate limits", async () => {
    stubFetch(() => json({ error: { code: "rate_limited", message: "Too many requests" } }, 429, { "Retry-After": "7" }));
    const error = await failureOf(createTransfer("b", 1, "k"));
    expect(error.retryAfterSeconds).toBe(7);
  });

  it("maps a network failure to status 0", async () => {
    stubFetch(() => {
      throw new TypeError("Failed to fetch");
    });
    const error = await failureOf(getMyWallet());
    expect(error.status).toBe(0);
    expect(error.code).toBe("network_error");
  });

  it("signs the user out on 401 for authenticated calls", async () => {
    let signedOut = 0;
    configureApi({ getToken: () => "expired", onUnauthorized: () => (signedOut += 1) });
    stubFetch(() => json({ error: { code: "token_expired", message: "Token has expired" } }, 401));
    await failureOf(getMyWallet());
    expect(signedOut).toBe(1);
  });
});
