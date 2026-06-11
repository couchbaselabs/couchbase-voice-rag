import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Toaster } from "sonner";

import { ErrorBoundary } from "@/components/ErrorBoundary";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Couchbase Realtime Voice RAG",
  description: "Real-time voice RAG powered by Couchbase Vector Search and OpenAI Realtime API",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${geistSans.variable} ${geistMono.variable} bg-[#0a0a0a] text-gray-100 antialiased`}
      >
        <ErrorBoundary>{children}</ErrorBoundary>
        <Toaster theme="dark" position="top-right" richColors />
      </body>
    </html>
  );
}
