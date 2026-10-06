export class ApiError extends Error {
  readonly code: string;
  readonly lineIndex: number | null;

  constructor(code: string, message: string, lineIndex: number | null) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.lineIndex = lineIndex;
  }
}

type ErrorEnvelope = {
  error?: {
    code?: unknown;
    message?: unknown;
    line_index?: unknown;
  };
};

export async function apiGet<T>(path: string, userId: number | null): Promise<T> {
  return apiRequest<T>(path, userId, "GET");
}

export async function apiSend<T>(
  path: string,
  userId: number,
  method: "POST" | "PUT",
  body: unknown,
): Promise<T> {
  return apiRequest<T>(path, userId, method, body);
}

export function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed";
}

async function apiRequest<T>(
  path: string,
  userId: number | null,
  method: "GET" | "POST" | "PUT",
  body?: unknown,
): Promise<T> {
  const headers = new Headers({ Accept: "application/json" });
  if (userId !== null) {
    headers.set("X-User-Id", String(userId));
  }
  if (body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    throw new Error("Request failed", { cause });
  }
  if (!response.ok) {
    throw await readError(response);
  }
  return (await response.json()) as T;
}

async function readError(response: Response): Promise<Error> {
  let body: ErrorEnvelope;
  try {
    body = (await response.json()) as ErrorEnvelope;
  } catch {
    return new Error("Request failed");
  }
  const error = body.error;
  if (
    error !== undefined &&
    typeof error.code === "string" &&
    typeof error.message === "string" &&
    (error.line_index === null || typeof error.line_index === "number")
  ) {
    return new ApiError(error.code, error.message, error.line_index);
  }
  return new Error("Request failed");
}
