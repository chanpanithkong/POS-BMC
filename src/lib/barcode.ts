import type { BarcodeSymbology } from "@/types";

/** GS1 mod-10 check digit for the digits preceding the check digit. */
function gs1Check(body: string) {
  const sum = body
    .split("")
    .reverse()
    .reduce((acc, ch, i) => acc + Number(ch) * (i % 2 === 0 ? 3 : 1), 0);
  return String((10 - (sum % 10)) % 10);
}

export const ean13CheckDigit = (body12: string) => gs1Check(body12);

const LENGTH: Partial<Record<BarcodeSymbology, number>> = { EAN13: 13, EAN8: 8, UPCA: 12 };
const LABEL: Record<BarcodeSymbology, string> = { EAN13: "EAN-13", EAN8: "EAN-8", UPCA: "UPC-A", CODE128: "Code 128" };

/** Returns an error message, or null if the barcode is valid for its symbology (BR-PRD-003). */
export function validateBarcode(value: string, symbology: BarcodeSymbology): string | null {
  if (!value) return "Barcode is required.";
  if (symbology === "CODE128") {
    // eslint-disable-next-line no-control-regex
    return /^[\x00-\x7f]{1,64}$/.test(value) ? null : "Code 128 values must be plain ASCII, up to 64 characters.";
  }
  const length = LENGTH[symbology] as number;
  if (!new RegExp(`^\\d{${length}}$`).test(value)) return `${LABEL[symbology]} must be ${length} digits.`;
  return gs1Check(value.slice(0, -1)) === value.slice(-1) ? null : `Invalid ${LABEL[symbology]} check digit`;
}

export function detectSymbology(value: string): BarcodeSymbology {
  if (/^\d{13}$/.test(value)) return "EAN13";
  if (/^\d{12}$/.test(value)) return "UPCA";
  if (/^\d{8}$/.test(value)) return "EAN8";
  return "CODE128";
}
