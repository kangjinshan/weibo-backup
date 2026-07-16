import assert from "node:assert/strict";
import test from "node:test";

import { fillCookieInput } from "../page-fill.js";

function installFakeDom({ modalOpen = true, fieldPresent = true } = {}) {
  const events = [];
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

  return { field, events };
}

test.afterEach(() => {
  delete globalThis.document;
  delete globalThis.Event;
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
