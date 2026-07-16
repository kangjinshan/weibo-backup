import assert from "node:assert/strict";
import test from "node:test";

import { buildCookieHeader } from "../cookie-utils.js";

const NOW = 2_000;

test("filters expired cookies and keeps session cookies", () => {
  const header = buildCookieHeader(
    [
      { name: "SESSION", value: "kept" },
      { name: "OLD", value: "discarded", expirationDate: NOW - 1 },
      { name: "FUTURE", value: "kept", expirationDate: NOW + 1 },
    ],
    [],
    NOW,
  );

  assert.equal(header, "FUTURE=kept; SESSION=kept");
});

test("prefers weibo.cn when both domains contain the same cookie name", () => {
  const header = buildCookieHeader(
    [{ name: "SUB", value: "cn-value" }],
    [{ name: "SUB", value: "com-value" }],
    NOW,
  );

  assert.equal(header, "SUB=cn-value");
});

test("includes unique cookies from both Weibo domains", () => {
  const header = buildCookieHeader(
    [{ name: "CN_ONLY", value: "cn" }],
    [{ name: "COM_ONLY", value: "com" }],
    NOW,
  );

  assert.equal(header, "CN_ONLY=cn; COM_ONLY=com");
});

test("sorts names and ignores malformed cookie records", () => {
  const header = buildCookieHeader(
    [
      { name: "z", value: "last" },
      { name: "", value: "empty-name" },
      { name: "a", value: "first" },
      { name: "NO_VALUE" },
      null,
    ],
    [],
    NOW,
  );

  assert.equal(header, "a=first; z=last");
});

test("returns an empty string when no usable cookies remain", () => {
  const header = buildCookieHeader(
    [{ name: "OLD", value: "discarded", expirationDate: NOW }],
    [],
    NOW,
  );

  assert.equal(header, "");
});
