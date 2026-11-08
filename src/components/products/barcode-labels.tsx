"use client";

import { Printer } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { printElement } from "@/lib/export";
import { formatUsd } from "@/lib/format";
import type { BarcodeSymbology } from "@/types";

const L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"];
const GCODES = ["0100111", "0110011", "0011011", "0100001", "0011101", "0111001", "0000101", "0010001", "0001001", "0010111"];
const R = L.map((p) => p.split("").map((b) => (b === "0" ? "1" : "0")).join(""));
const PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"];

function ean13Bits(code: string) {
  const digits = code.split("").map(Number);
  const parity = PARITY[digits[0]];
  const left = digits.slice(1, 7).map((d, i) => (parity[i] === "L" ? L[d] : GCODES[d])).join("");
  const right = digits.slice(7).map((d) => R[d]).join("");
  return `101${left}01010${right}101`;
}

function Bars({ value, symbology }: { value: string; symbology: BarcodeSymbology }) {
  if (symbology !== "EAN13" || value.length !== 13) {
    return <p className="border border-dashed py-3 text-center font-mono text-[10px]">Barcode image for {symbology} is rendered by the label printer agent.</p>;
  }
  const bits = ean13Bits(value);
  return (
    <svg viewBox={`0 0 ${bits.length} 40`} className="h-10 w-full" preserveAspectRatio="none" role="img" aria-label={`Barcode ${value}`}>
      {bits.split("").map((b, i) => (b === "1" ? <rect key={i} x={i} y={0} width={1} height={40} fill="#000" /> : null))}
    </svg>
  );
}

export interface LabelItem {
  barcode: string;
  symbology: BarcodeSymbology;
  name: string;
  price: number;
}

export function BarcodeLabelDialog({ open, onOpenChange, items }: { open: boolean; onOpenChange: (open: boolean) => void; items: LabelItem[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const [copies, setCopies] = useState(1);
  const repeated = items.flatMap((item) => Array.from({ length: Math.max(1, copies) }, () => item));
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader><DialogTitle>Print barcode labels</DialogTitle><DialogDescription>{items.length} barcode{items.length === 1 ? "" : "s"}</DialogDescription></DialogHeader>
        <div className="space-y-1"><Label htmlFor="copies">Copies of each</Label><Input id="copies" type="number" min={1} max={100} value={copies} onChange={(e) => setCopies(Number(e.target.value))} className="w-24" /></div>
        <div ref={ref} style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }} className="max-h-72 overflow-y-auto rounded-md bg-white p-2 text-black">
          {repeated.slice(0, 120).map((item, i) => (
            <div key={i} style={{ border: "1px solid #ddd", padding: 4, fontSize: 10 }}>
              <p className="truncate font-medium">{item.name}</p>
              <Bars value={item.barcode} symbology={item.symbology} />
              <p className="flex justify-between font-mono"><span>{item.barcode}</span><span className="font-bold">{formatUsd(item.price)}</span></p>
            </div>
          ))}
        </div>
        <DialogFooter><Button onClick={() => printElement(ref.current)}><Printer />Print</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
