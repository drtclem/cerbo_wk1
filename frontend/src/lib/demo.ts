/** Demo login helpers. No money logic. */

export const STORAGE_KEY = "cerbo.userId";

export const DEMO_PROVIDER_NAME = "Dr. Maya Patel";

export type DemoUser = {
  id: number;
  name: string;
  role: string;
};

/** Stored user id when present and valid; otherwise null (show login). */
export function storedUserId(users: DemoUser[], raw: string | null): number | null {
  if (raw === null || !/^\d+$/.test(raw)) {
    return null;
  }
  const stored = Number(raw);
  return users.some((user) => user.id === stored) ? stored : null;
}

/** Default demo login target: Dr. Maya Patel. */
export function demoLoginUserId(users: DemoUser[]): number {
  const provider = users.find((user) => user.name === DEMO_PROVIDER_NAME);
  if (provider === undefined) {
    throw new Error(`${DEMO_PROVIDER_NAME} is missing from the user list`);
  }
  return provider.id;
}

/**
 * POST /api/demo/reset. A 404 is ignored so local `uvicorn app.main:app`
 * without DEMO_MODE still lets login/logout work.
 */
export async function postDemoReset(
  fetchImpl: typeof fetch = fetch,
): Promise<"reset" | "unavailable"> {
  let response: Response;
  try {
    response = await fetchImpl("/api/demo/reset", { method: "POST" });
  } catch (cause) {
    throw new Error("Request failed", { cause });
  }
  if (response.status === 404) {
    return "unavailable";
  }
  if (response.status === 204) {
    return "reset";
  }
  throw new Error(`Demo reset failed (${response.status})`);
}
