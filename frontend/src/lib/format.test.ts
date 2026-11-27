import { describe, expect, it } from "vitest";
import { isUuid, newIdempotencyKey, shortId } from "./format";

describe("format helpers", () => {
  it("recognises UUIDs", () => {
    expect(isUuid("3f2a9c1e-5b7d-4e21-9a0c-1d2e3f4a5b6c")).toBe(true);
    expect(isUuid("  3F2A9C1E-5B7D-4E21-9A0C-1D2E3F4A5B6C ")).toBe(true);
    expect(isUuid("not-a-uuid")).toBe(false);
    expect(isUuid("")).toBe(false);
  });

  it("shortens long ids and leaves short ones alone", () => {
    expect(shortId("3f2a9c1e-5b7d-4e21-9a0c-1d2e3f4a5b6c")).toBe("3f2a9c1e…5b6c");
    expect(shortId("abc")).toBe("abc");
  });

  it("generates request keys the backend accepts", () => {
    const key = newIdempotencyKey();
    expect(/^[A-Za-z0-9._:-]{1,255}$/.test(key)).toBe(true);
    expect(newIdempotencyKey() === key).toBe(false);
  });
});
