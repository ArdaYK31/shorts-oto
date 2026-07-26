import { createHash, timingSafeEqual } from "crypto";
import { cookies } from "next/headers";

const COOKIE = "atelier_session";

function expectedToken(): string {
  const secret = process.env.AUTH_COOKIE_SECRET || "atelier-dev-secret";
  const password = process.env.AUTH_PASSWORD || "atelier";
  return createHash("sha256").update(`${secret}:${password}`).digest("hex");
}

export function checkPassword(password: string): boolean {
  const want = process.env.AUTH_PASSWORD || "atelier";
  try {
    const a = Buffer.from(password);
    const b = Buffer.from(want);
    if (a.length !== b.length) return false;
    return timingSafeEqual(a, b);
  } catch {
    return false;
  }
}

export async function setSessionCookie() {
  const jar = await cookies();
  jar.set(COOKIE, expectedToken(), {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 14,
  });
}

export async function clearSessionCookie() {
  const jar = await cookies();
  jar.delete(COOKIE);
}

export async function isAuthenticated(): Promise<boolean> {
  const jar = await cookies();
  const val = jar.get(COOKIE)?.value;
  if (!val) return false;
  try {
    const a = Buffer.from(val);
    const b = Buffer.from(expectedToken());
    if (a.length !== b.length) return false;
    return timingSafeEqual(a, b);
  } catch {
    return false;
  }
}

