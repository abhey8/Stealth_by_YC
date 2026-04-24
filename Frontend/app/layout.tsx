import type { Metadata } from "next";
import { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Financial Advisor Dashboard",
  description: "Portfolio intelligence dashboard with market, sector, and risk analysis."
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
