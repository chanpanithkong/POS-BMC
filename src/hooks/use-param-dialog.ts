"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";

/**
 * Dialog open state that also opens when the URL carries `?name=1`, so other
 * screens can deep-link to a create form. State adjusts during render, which
 * also handles routes kept alive by Activity.
 */
export function useParamDialog(name: string, allowed: boolean) {
  const requested = useSearchParams().get(name) === "1" && allowed;
  const [open, setOpen] = useState(requested);
  const [seen, setSeen] = useState(requested);
  if (requested !== seen) {
    setSeen(requested);
    if (requested) setOpen(true);
  }
  return [open, setOpen] as const;
}
