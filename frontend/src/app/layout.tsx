import type { Metadata } from "next";
import { Geist, Geist_Mono, Noto_Sans_Khmer } from "next/font/google";
import { AppProviders } from "@/components/shared/app-providers";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const notoKhmer = Noto_Sans_Khmer({
  variable: "--font-khmer",
  subsets: ["khmer"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: { default: "ABC Mart POS and Inventory", template: "%s | ABC Mart" },
  description: "Point of sale and inventory management for retail branches.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" suppressHydrationWarning className={`${geistSans.variable} ${geistMono.variable} ${notoKhmer.variable} h-full antialiased`}>
      <body className="min-h-full">
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
