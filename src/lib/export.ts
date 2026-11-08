import { strFromU8, strToU8, unzipSync, zipSync } from "fflate";

export interface ExportColumn {
  header: string;
  key: string;
}

export type ExportRow = Record<string, string | number | null | undefined>;

function download(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function csvCell(value: unknown) {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function toCsv(columns: ExportColumn[], rows: ExportRow[]) {
  return [columns.map((c) => csvCell(c.header)).join(","), ...rows.map((row) => columns.map((c) => csvCell(row[c.key])).join(","))].join("\r\n");
}

/** UTF-8 with BOM so Khmer text opens correctly in Excel. */
export function exportCsv(fileName: string, columns: ExportColumn[], rows: ExportRow[]) {
  download(new Blob(["﻿", toCsv(columns, rows)], { type: "text/csv;charset=utf-8" }), `${fileName}.csv`);
}

const xml = (value: string) => value.replace(/[<>&"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" })[c] as string);

function columnName(index: number) {
  let name = "";
  for (let i = index + 1; i > 0; i = Math.floor((i - 1) / 26)) name = String.fromCharCode(65 + ((i - 1) % 26)) + name;
  return name;
}

/** Writes a real .xlsx workbook with numeric cells (SRS 16.4). */
export function exportXlsx(fileName: string, columns: ExportColumn[], rows: ExportRow[]) {
  const cell = (ref: string, value: unknown) => {
    if (value === null || value === undefined || value === "") return "";
    if (typeof value === "number") return `<c r="${ref}"><v>${value}</v></c>`;
    return `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${xml(String(value))}</t></is></c>`;
  };
  const header = `<row r="1">${columns.map((c, i) => cell(`${columnName(i)}1`, c.header)).join("")}</row>`;
  const body = rows.map((row, r) => `<row r="${r + 2}">${columns.map((c, i) => cell(`${columnName(i)}${r + 2}`, row[c.key])).join("")}</row>`).join("");
  const files = {
    "[Content_Types].xml": strToU8('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'),
    "_rels/.rels": strToU8('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'),
    "xl/workbook.xml": strToU8('<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Export" sheetId="1" r:id="rId1"/></sheets></workbook>'),
    "xl/_rels/workbook.xml.rels": strToU8('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'),
    "xl/worksheets/sheet1.xml": strToU8(`<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>${header}${body}</sheetData></worksheet>`),
  };
  download(new Blob([zipSync(files) as BlobPart], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }), `${fileName}.xlsx`);
}

/** Parses CSV text into row objects keyed by header. */
export function parseCsv(text: string): Record<string, string>[] {
  const rows: string[][] = [];
  let field = "";
  let row: string[] = [];
  let quoted = false;
  const source = text.replace(/^﻿/, "");
  for (let i = 0; i < source.length; i++) {
    const ch = source[i];
    if (quoted) {
      if (ch === '"' && source[i + 1] === '"') {
        field += '"';
        i++;
      } else if (ch === '"') quoted = false;
      else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") {
      row.push(field);
      field = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && source[i + 1] === "\n") i++;
      row.push(field);
      field = "";
      if (row.some((c) => c !== "")) rows.push(row);
      row = [];
    } else field += ch;
  }
  if (field || row.length) {
    row.push(field);
    if (row.some((c) => c !== "")) rows.push(row);
  }
  const [header, ...data] = rows;
  if (!header) return [];
  return data.map((cells) => Object.fromEntries(header.map((h, i) => [h.trim(), (cells[i] ?? "").trim()])));
}

/** Reads the first sheet of an .xlsx file in the browser. */
export function parseXlsx(buffer: ArrayBuffer): Record<string, string>[] {
  const files = unzipSync(new Uint8Array(buffer));
  const parser = new DOMParser();
  const shared = files["xl/sharedStrings.xml"] ? [...parser.parseFromString(strFromU8(files["xl/sharedStrings.xml"]), "application/xml").getElementsByTagName("si")].map((si) => si.textContent ?? "") : [];
  const sheetName = Object.keys(files).filter((f) => /^xl\/worksheets\/sheet\d+\.xml$/.test(f)).sort()[0];
  if (!sheetName) return [];
  const sheet = parser.parseFromString(strFromU8(files[sheetName]), "application/xml");
  const table = [...sheet.getElementsByTagName("row")].map((row) => {
    const cells: string[] = [];
    for (const c of row.getElementsByTagName("c")) {
      const ref = c.getAttribute("r") ?? "";
      const letters = ref.replace(/\d+/g, "");
      let index = 0;
      for (const l of letters) index = index * 26 + (l.charCodeAt(0) - 64);
      const type = c.getAttribute("t");
      const raw = c.getElementsByTagName("v")[0]?.textContent ?? c.getElementsByTagName("t")[0]?.textContent ?? "";
      cells[index - 1] = type === "s" ? shared[Number(raw)] ?? "" : raw;
    }
    return cells;
  });
  const [header, ...data] = table;
  if (!header) return [];
  return data.filter((r) => r.some(Boolean)).map((cells) => Object.fromEntries(header.map((h, i) => [String(h).trim(), String(cells[i] ?? "").trim()])));
}

export async function sha256(buffer: ArrayBuffer) {
  const hash = await crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function printRoot(html: string, className: string) {
  document.getElementById("print-root")?.remove();
  const root = document.createElement("div");
  root.id = "print-root";
  root.className = className;
  root.innerHTML = html;
  document.body.append(root);
  document.body.classList.add("printing");
  const cleanup = () => {
    root.remove();
    document.body.classList.remove("printing");
    window.removeEventListener("afterprint", cleanup);
  };
  window.addEventListener("afterprint", cleanup);
  window.print();
}

/** Prints one element, for receipts, invoices and notes. */
export function printElement(element: HTMLElement | null, className = "") {
  if (element) printRoot(element.innerHTML, className);
}

/** Prints every filtered row, not just the current page. */
export function printTable(title: string, columns: ExportColumn[], rows: ExportRow[], meta = "") {
  const head = columns.map((c) => `<th>${xml(c.header)}</th>`).join("");
  const body = rows.map((row) => `<tr>${columns.map((c) => `<td>${xml(String(row[c.key] ?? ""))}</td>`).join("")}</tr>`).join("");
  printRoot(`<h1 style="font-size:16px;font-weight:600">${xml(title)}</h1>${meta ? `<p>${xml(meta)}</p>` : ""}<p>Printed ${xml(new Date().toLocaleString("en-GB"))}</p><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`, "report");
}
