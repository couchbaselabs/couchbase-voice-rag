"use client";

import { useRouter } from "next/navigation";
import LoginForm from "@/components/LoginForm";
import { useAuth } from "@/hooks/useAuth";
import { useEffect } from "react";

export default function LoginPage() {
  const router = useRouter();
  const { username, loading, login, mustChangePassword } = useAuth();

  useEffect(() => {
    if (!loading && username) {
      if (mustChangePassword) {
        router.replace("/change-password?forced=1");
      } else {
        router.replace("/chat");
      }
    }
  }, [loading, username, mustChangePassword, router]);

  const handleLogin = async (user: string, password: string) => {
    const data = await login(user, password);
    if (data.must_change_password) {
      router.replace("/change-password?forced=1");
    } else {
      router.replace("/chat");
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a]">
        <div className="text-gray-400">Loading...</div>
      </div>
    );
  }

  return <LoginForm onLogin={handleLogin} />;
}
