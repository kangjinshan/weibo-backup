import { buildCookieHeader } from "./cookie-utils.js";
import { fillCookieInput } from "./page-fill.js";

const DASHBOARD_ORIGIN = "https://weibo.jinshanweb.com:8765";
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

class OperationError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

function showStatus(message, type = "") {
  status.textContent = message;
  status.className = type ? `status ${type}` : "status";
}

function setBusy(busy) {
  button.disabled = busy;
  button.textContent = busy ? "正在获取…" : "获取并填入";
}

function isTargetDashboard(tab) {
  if (!Number.isInteger(tab?.id) || typeof tab.url !== "string") {
    return false;
  }
  try {
    return new URL(tab.url).origin === DASHBOARD_ORIGIN;
  } catch {
    return false;
  }
}

async function getActiveTab() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    return tab;
  } catch {
    throw new OperationError("permission");
  }
}

async function getDomainCookies(domain) {
  try {
    return await chrome.cookies.getAll({ domain });
  } catch {
    throw new OperationError("permission");
  }
}

async function fillActiveDashboard(tabId, cookieHeader) {
  let injectionResults;
  try {
    injectionResults = await chrome.scripting.executeScript({
      target: { tabId },
      func: fillCookieInput,
      args: [cookieHeader],
    });
  } catch {
    throw new OperationError("injection");
  }

  const result = injectionResults?.[0]?.result;
  if (!result?.ok) {
    throw new OperationError(
      result?.reason === "settings_closed" ? "settings_closed" : "injection",
    );
  }
}

async function handleFill() {
  setBusy(true);
  showStatus("正在读取微博 Cookie…");
  try {
    const tab = await getActiveTab();
    if (!isTargetDashboard(tab)) {
      throw new OperationError("wrong_page");
    }

    const [weiboCnCookies, weiboComCookies] = await Promise.all([
      getDomainCookies("weibo.cn"),
      getDomainCookies("weibo.com"),
    ]);
    const cookieHeader = buildCookieHeader(weiboCnCookies, weiboComCookies);
    if (!cookieHeader) {
      throw new OperationError("no_cookies");
    }

    await fillActiveDashboard(tab.id, cookieHeader);
    showStatus("已填入，请检查并在后台手动保存。", "success");
  } catch (error) {
    const code = error instanceof OperationError ? error.code : "generic";
    showStatus(ERROR_MESSAGES[code] ?? ERROR_MESSAGES.generic, "error");
  } finally {
    setBusy(false);
  }
}

button.addEventListener("click", handleFill);
