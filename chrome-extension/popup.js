import { fillCookieInput } from "./page-fill.js";
import { OperationError, coordinateCookieFill } from "./popup-coordinator.js";

const button = document.querySelector("#fillCookieButton");
const status = document.querySelector("#status");

const ERROR_MESSAGES = {
  wrong_page: "请先打开 https://weibo.jinshanweb.com:8765 的备份后台。",
  settings_closed: "请先在备份后台打开“备份设置”。",
  no_cookies: "未找到可用的微博 Cookie，请先登录或重新登录微博。",
  permission: "Chrome 未允许读取或填入，请检查插件权限并重新加载插件。",
  injection: "填入失败，请刷新备份后台后重试。",
  generic: "操作失败，请重新登录微博、刷新后台后重试。",
};

function showStatus(message, type = "") {
  status.textContent = message;
  status.className = type ? `status ${type}` : "status";
}

function setBusy(busy) {
  button.disabled = busy;
  button.textContent = busy ? "正在获取…" : "获取并填入";
}

async function handleFill() {
  setBusy(true);
  showStatus("正在读取微博 Cookie…");
  try {
    await coordinateCookieFill(chrome, fillCookieInput);
    showStatus("已填入，请检查并在后台手动保存。", "success");
  } catch (error) {
    const code = error instanceof OperationError ? error.code : "generic";
    showStatus(ERROR_MESSAGES[code] ?? ERROR_MESSAGES.generic, "error");
  } finally {
    setBusy(false);
  }
}

button.addEventListener("click", handleFill);
