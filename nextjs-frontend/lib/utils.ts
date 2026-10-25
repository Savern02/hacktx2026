import { AuthJwtLoginError, RegisterRegisterError } from "@/app/clientService";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function getErrorMessage(
  error: RegisterRegisterError | AuthJwtLoginError,
): string {
  // No detail means the request never got an answer (e.g. the backend is down).
  let errorMessage =
    "Equa can't reach the server right now. Please try again in a moment.";

  if (typeof error.detail === "string") {
    // If detail is a string, use it directly
    errorMessage = error.detail;
  } else if (typeof error.detail === "object" && "reason" in error.detail) {
    // If detail is an object with a 'reason' key, use that
    errorMessage = error.detail["reason"];
  }

  return errorMessage;
}
