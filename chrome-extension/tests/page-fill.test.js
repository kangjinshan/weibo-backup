import assert from "node:assert/strict";
import test from "node:test";

import { fillCookieInput } from "../page-fill.js";

function installFakeDom({
  modalOpen = true,
  fieldPresent = true,
  origin = "https://weibo.jinshanweb.com:8765",
} = {}) {
  const events = [];
  let queryCount = 0;
  const field = fieldPresent
    ? {
        value: "",
        dispatchEvent(event) {
          events.push({ type: event.type, bubbles: event.bubbles });
          return true;
        },
      }
    : null;
  const modal = {
    classList: {
      contains(name) {
        return name === "active" && modalOpen;
      },
    },
  };

  globalThis.document = {
    querySelector(selector) {
      queryCount += 1;
      if (selector === "#backupModal") return modal;
      if (selector === "#configCookieInput") return field;
      return null;
    },
  };
  globalThis.Event = class FakeEvent {
    constructor(type, options = {}) {
      this.type = type;
      this.bubbles = Boolean(options.bubbles);
    }
  };
  globalThis.location = { origin };

  return {
    field,
    events,
    get queryCount() {
      return queryCount;
    },
  };
}

test.afterEach(() => {
  delete globalThis.document;
  delete globalThis.Event;
  delete globalThis.location;
});

test("fills the Cookie field and emits input and change events", () => {
  const { field, events } = installFakeDom();

  const result = fillCookieInput("SUB=secret");

  assert.deepEqual(result, { ok: true });
  assert.equal(field.value, "SUB=secret");
  assert.deepEqual(events, [
    { type: "input", bubbles: true },
    { type: "change", bubbles: true },
  ]);
});

test("refuses to fill when the settings modal is closed", () => {
  const { field, events } = installFakeDom({ modalOpen: false });

  const result = fillCookieInput("SUB=secret");

  assert.deepEqual(result, { ok: false, reason: "settings_closed" });
  assert.equal(field.value, "");
  assert.deepEqual(events, []);
});

test("refuses to fill when the Cookie field is missing", () => {
  installFakeDom({ fieldPresent: false });

  const result = fillCookieInput("SUB=secret");

  assert.deepEqual(result, { ok: false, reason: "settings_closed" });
});

test("does not inspect or fill a navigated non-dashboard page", () => {
  const fakeDom = installFakeDom({
    origin: "https://example.com",
  });

  const result = fillCookieInput("SUB=secret");

  assert.deepEqual(result, { ok: false, reason: "wrong_page" });
  assert.equal(fakeDom.queryCount, 0);
  assert.equal(fakeDom.field.value, "");
  assert.deepEqual(fakeDom.events, []);
});
