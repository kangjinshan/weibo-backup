export function fillCookieInput(cookieHeader) {
  if (location.origin !== "https://weibo.jinshanweb.com:8765") {
    return { ok: false, reason: "wrong_page" };
  }

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
