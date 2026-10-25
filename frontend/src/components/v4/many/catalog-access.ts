"use client";

/**
 * Who may run a catalog: read once from GET /auth/me/usage (and again when
 * usage changes). Pilot runs any size; a work-email account has its free
 * parts; personal email keeps single checks. The server enforces all of it;
 * this only decides what the screens show up front.
 */
import * as React from "react";
import { fetchUsage } from "./catalog-api";
import { catalogAccess, type CatalogAccess } from "./catalog-model";

export function useCatalogAccess(): CatalogAccess {
  const [access, setAccess] = React.useState<CatalogAccess>({ kind: "loading" });
  React.useEffect(() => {
    let live = true;
    const read = () =>
      fetchUsage().then(
        (u) => live && setAccess(catalogAccess(u)),
        () => live && setAccess({ kind: "unknown" }),
      );
    void read();
    window.addEventListener("proofshape:usage-changed", read);
    return () => {
      live = false;
      window.removeEventListener("proofshape:usage-changed", read);
    };
  }, []);
  return access;
}

/** Whether the Many parts screens open for this account (the catalog run and its results). */
export function opensCatalog(a: CatalogAccess): boolean {
  return a.kind === "pilot" || a.kind === "free" || a.kind === "unknown";
}
