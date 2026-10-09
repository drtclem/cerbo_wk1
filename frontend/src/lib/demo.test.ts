import { expect, test, vi } from "vitest";

import {
  DEMO_PROVIDER_NAME,
  demoLoginUserId,
  postDemoReset,
  storedUserId,
} from "./demo";

const USERS = [
  { id: 1, name: "Dr. Maya Patel", role: "provider" },
  { id: 2, name: "Jane Doe", role: "patient" },
  { id: 3, name: "Sam Lee", role: "patient" },
  { id: 4, name: "Cerbo Admin", role: "admin" },
] as const;

test("storedUserId returns null when nothing is stored so the login screen shows", () => {
  expect(storedUserId([...USERS], null)).toBeNull();
  expect(storedUserId([...USERS], "")).toBeNull();
  expect(storedUserId([...USERS], "abc")).toBeNull();
});

test("storedUserId returns the stored id when it matches a listed user", () => {
  expect(storedUserId([...USERS], "2")).toBe(2);
});

test("storedUserId returns null when the stored id is unknown", () => {
  expect(storedUserId([...USERS], "999")).toBeNull();
});

test("demoLoginUserId selects Dr. Maya Patel", () => {
  expect(DEMO_PROVIDER_NAME).toBe("Dr. Maya Patel");
  expect(demoLoginUserId([...USERS])).toBe(1);
});

test("postDemoReset treats 204 as reset and 404 as unavailable", async () => {
  const ok = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
  await expect(postDemoReset(ok)).resolves.toBe("reset");
  expect(ok).toHaveBeenCalledWith("/api/demo/reset", { method: "POST" });

  const missing = vi.fn().mockResolvedValue(new Response(null, { status: 404 }));
  await expect(postDemoReset(missing)).resolves.toBe("unavailable");
});

test("postDemoReset rejects unexpected status codes", async () => {
  const bad = vi.fn().mockResolvedValue(new Response(null, { status: 500 }));
  await expect(postDemoReset(bad)).rejects.toThrow(/500/);
});
