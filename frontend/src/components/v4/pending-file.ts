/**
 * Hands a picked or dropped CAD file from wherever it was chosen (top bar,
 * Home, the start page) to the check page, across a client-side navigation.
 * Memory only: nothing is written to disk or sent anywhere until the check runs.
 */
let pending: File | null = null;

export function setPendingFile(file: File): void {
  pending = file;
}

export function takePendingFile(): File | null {
  const file = pending;
  pending = null;
  return file;
}

/** A share link pasted on Home, for the check page to import (memory only, never in a URL). */
let pendingLink: string | null = null;

export function setPendingLink(url: string): void {
  pendingLink = url;
}

export function takePendingLink(): string | null {
  const url = pendingLink;
  pendingLink = null;
  return url;
}

export const CAD_ACCEPT = ".step,.stp,.stl,.iges,.igs";
