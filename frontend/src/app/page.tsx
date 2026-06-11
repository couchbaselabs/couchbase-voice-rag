"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { getMe } from "@/lib/api";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    getMe()
      .then(() => router.replace("/chat"))
      .catch(() => router.replace("/login"));
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a]">
      <div className="text-gray-400">Loading...</div>
    </div>
  );
}
