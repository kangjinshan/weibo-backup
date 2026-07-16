function isUsableCookie(cookie, nowSeconds) {
  if (!cookie || typeof cookie.name !== "string" || cookie.name.length === 0) {
    return false;
  }
  if (typeof cookie.value !== "string") {
    return false;
  }
  return (
    typeof cookie.expirationDate !== "number" ||
    cookie.expirationDate > nowSeconds
  );
}

function mergeCookies(target, cookies, nowSeconds) {
  for (const cookie of cookies) {
    if (isUsableCookie(cookie, nowSeconds)) {
      target.set(cookie.name, cookie.value);
    }
  }
}

export function buildCookieHeader(
  weiboCnCookies,
  weiboComCookies,
  nowSeconds = Date.now() / 1_000,
) {
  const valuesByName = new Map();
  mergeCookies(valuesByName, weiboComCookies, nowSeconds);
  mergeCookies(valuesByName, weiboCnCookies, nowSeconds);

  return [...valuesByName.entries()]
    .sort(([leftName], [rightName]) =>
      leftName < rightName ? -1 : leftName > rightName ? 1 : 0,
    )
    .map(([name, value]) => `${name}=${value}`)
    .join("; ");
}
