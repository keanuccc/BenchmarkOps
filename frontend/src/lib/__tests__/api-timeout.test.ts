// Tests for the API client's timeout + network-error translation.
// Runs under Node's built-in test runner:
//   node --experimental-strip-types --test src/lib/__tests__/api-timeout.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { request, ApiRequestError } from "../api.ts";

const NEVER: Promise<Response> = new Promise<Response>(() => {
  /* never resolves nor rejects — simulates a backend that is stuck on a write lock */
});

test("timeout: never-resolving fetch rejects with code 'timeout'", async () => {
  const original = globalThis.fetch;
  // Simulate a backend that never responds: the promise stays pending, and when
  // request() aborts the signal (our 50ms timeout) the fetch rejects with AbortError.
  globalThis.fetch = ((_input: unknown, init?: { signal?: AbortSignal }) =>
    new Promise<Response>((_resolve, reject) => {
      const sig = init?.signal;
      if (sig) {
        sig.addEventListener("abort", () =>
          reject(new DOMException("Aborted", "AbortError")),
        );
      }
    })) as unknown as typeof fetch;
  try {
    await request("/ping", { timeoutMs: 50 });
    assert.fail("expected request to reject on timeout");
  } catch (err) {
    assert.ok(err instanceof ApiRequestError, "should be ApiRequestError, not raw TypeError");
    assert.equal((err as ApiRequestError).code, "timeout");
  } finally {
    globalThis.fetch = original;
  }
});

test("network_error: fetch rejecting with TypeError is translated", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = (() =>
    Promise.reject(new TypeError("Failed to fetch"))) as unknown as typeof fetch;
  try {
    await request("/ping", { timeoutMs: 5000 });
    assert.fail("expected request to reject");
  } catch (err) {
    assert.ok(err instanceof ApiRequestError, "should be ApiRequestError, not raw TypeError");
    assert.equal((err as ApiRequestError).code, "network_error");
  } finally {
    globalThis.fetch = original;
  }
});

test("ok: 200 response is parsed normally", async () => {
  const original = globalThis.fetch;
  const fake = {
    ok: true,
    status: 200,
    json: async () => ({ hello: "world" }),
  } as unknown as Response;
  globalThis.fetch = (() => Promise.resolve(fake)) as unknown as typeof fetch;
  try {
    const res = await request<{ hello: string }>("/ping", { timeoutMs: 5000 });
    assert.deepEqual(res, { hello: "world" });
  } finally {
    globalThis.fetch = original;
  }
});

test("http error: non-2xx still throws ApiRequestError with server body", async () => {
  const original = globalThis.fetch;
  const fake = {
    ok: false,
    status: 409,
    statusText: "Conflict",
    json: async () => ({ error: { code: "conflict", message: "已存在" } }),
  } as unknown as Response;
  globalThis.fetch = (() => Promise.resolve(fake)) as unknown as typeof fetch;
  try {
    await request("/ping", { timeoutMs: 5000 });
    assert.fail("expected request to reject on 409");
  } catch (err) {
    assert.ok(err instanceof ApiRequestError);
    assert.equal((err as ApiRequestError).status, 409);
    assert.equal((err as ApiRequestError).code, "conflict");
    assert.equal((err as ApiRequestError).message, "已存在");
  } finally {
    globalThis.fetch = original;
  }
});
