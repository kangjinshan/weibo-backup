import { buildCookieHeader } from "./cookie-utils.js";

export const DASHBOARD_ORIGIN = "https://weibo.jinshanweb.com:8765";

export class OperationError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
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

async function getActiveTab(chromeApi) {
  try {
    const [tab] = await chromeApi.tabs.query({ active: true, currentWindow: true });
    return tab;
  } catch {
    throw new OperationError("permission");
  }
}

async function getDomainCookies(chromeApi, domain) {
  try {
    return await chromeApi.cookies.getAll({ domain });
  } catch {
    throw new OperationError("permission");
  }
}

async function fillActiveDashboard(chromeApi, tabId, cookieHeader, fillCookieInput) {
  let injectionResults;
  try {
    injectionResults = await chromeApi.scripting.executeScript({
      target: { tabId },
      func: fillCookieInput,
      args: [cookieHeader],
    });
  } catch {
    throw new OperationError("injection");
  }

  const result = injectionResults?.[0]?.result;
  if (!result?.ok) {
    const code = ["wrong_page", "settings_closed"].includes(result?.reason)
      ? result.reason
      : "injection";
    throw new OperationError(code);
  }
}

export async function coordinateCookieFill(chromeApi, fillCookieInput) {
  const tab = await getActiveTab(chromeApi);
  if (!isTargetDashboard(tab)) {
    throw new OperationError("wrong_page");
  }

  const [weiboCnCookies, weiboComCookies] = await Promise.all([
    getDomainCookies(chromeApi, "weibo.cn"),
    getDomainCookies(chromeApi, "weibo.com"),
  ]);
  const cookieHeader = buildCookieHeader(weiboCnCookies, weiboComCookies);
  if (!cookieHeader) {
    throw new OperationError("no_cookies");
  }

  await fillActiveDashboard(chromeApi, tab.id, cookieHeader, fillCookieInput);
}
