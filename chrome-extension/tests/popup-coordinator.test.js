import assert from "node:assert/strict";
import test from "node:test";

import {
  DASHBOARD_ORIGIN,
  OperationError,
  coordinateCookieFill,
} from "../popup-coordinator.js";

function createChromeApi({
  tab = { id: 42, url: `${DASHBOARD_ORIGIN}/` },
  cookies = [{ name: "SUB", value: "value" }],
  cookieError,
  injectionResult = [{ result: { ok: true } }],
  injectionError,
} = {}) {
  const calls = { cookieReads: [], injections: [] };
  return {
    calls,
    api: {
      tabs: {
        async query() {
          return [tab];
        },
      },
      cookies: {
        async getAll(details) {
          calls.cookieReads.push(details);
          if (cookieError) throw cookieError;
          return cookies;
        },
      },
      scripting: {
        async executeScript(details) {
          calls.injections.push(details);
          if (injectionError) throw injectionError;
          return injectionResult;
        },
      },
    },
  };
}

test("wrong-origin active tab reads no Cookies and performs no injection", async () => {
  const { api, calls } = createChromeApi({
    tab: { id: 42, url: "https://example.com/settings" },
  });

  await assert.rejects(
    coordinateCookieFill(api, () => ({ ok: true })),
    (error) => error instanceof OperationError && error.code === "wrong_page",
  );

  assert.deepEqual(calls.cookieReads, []);
  assert.deepEqual(calls.injections, []);
});

test("rejects a wrong-page result returned by the injected function", async () => {
  const { api, calls } = createChromeApi({
    injectionResult: [{ result: { ok: false, reason: "wrong_page" } }],
  });

  await assert.rejects(
    coordinateCookieFill(api, () => ({ ok: true })),
    (error) => error instanceof OperationError && error.code === "wrong_page",
  );

  assert.equal(calls.injections.length, 1);
  assert.equal(calls.injections[0].target.tabId, 42);
  assert.equal(typeof calls.injections[0].func, "function");
});

test("Cookie and injection API errors expose safe error codes only", async (t) => {
  await t.test("Cookie read failure", async () => {
    const { api } = createChromeApi({
      cookieError: new Error("Cookie: SUB=raw-secret"),
    });

    await assert.rejects(
      coordinateCookieFill(api, () => ({ ok: true })),
      (error) =>
        error instanceof OperationError &&
        error.code === "permission" &&
        error.message === "permission" &&
        !String(error).includes("raw-secret"),
    );
  });

  await t.test("injection failure", async () => {
    const { api } = createChromeApi({
      injectionError: new Error("Cookie: SUB=raw-secret"),
    });

    await assert.rejects(
      coordinateCookieFill(api, () => ({ ok: true })),
      (error) =>
        error instanceof OperationError &&
        error.code === "injection" &&
        error.message === "injection" &&
        !String(error).includes("raw-secret"),
    );
  });

  await t.test("empty injection result", async () => {
    const { api } = createChromeApi({ injectionResult: [] });

    await assert.rejects(
      coordinateCookieFill(api, () => ({ ok: true })),
      (error) =>
        error instanceof OperationError &&
        error.code === "injection" &&
        error.message === "injection" &&
        !String(error).includes("Cookie:") &&
        !String(error).includes("raw-secret"),
    );
  });

  await t.test("unexpected injected failure reason", async () => {
    const { api } = createChromeApi({
      injectionResult: [
        {
          result: {
            ok: false,
            reason: "unexpected",
            value: "Cookie: SUB=raw-secret",
          },
        },
      ],
    });

    await assert.rejects(
      coordinateCookieFill(api, () => ({ ok: true })),
      (error) =>
        error instanceof OperationError &&
        error.code === "injection" &&
        error.message === "injection" &&
        !String(error).includes("Cookie:") &&
        !String(error).includes("raw-secret"),
    );
  });
});
