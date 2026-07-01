import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Single source of truth for class composition (clsx + tailwind-merge). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
