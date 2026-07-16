export function fillCookieInput(cookieHeader) {
  const modal = document.querySelector("#backupModal");
  const field = document.querySelector("#configCookieInput");
  if (!modal?.classList.contains("active") || !field) {
    return { ok: false, reason: "settings_closed" };
  }

  field.value = cookieHeader;
  field.dispatchEvent(new Event("input", { bubbles: true }));
  field.dispatchEvent(new Event("change", { bubbles: true }));
  return { ok: true };
}
