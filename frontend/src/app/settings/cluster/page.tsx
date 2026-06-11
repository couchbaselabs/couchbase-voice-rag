"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import SettingsForm from "@/components/SettingsForm";
import * as api from "@/lib/api";

export default function ClusterSettingsPage() {
  const router = useRouter();
  const { username, loading, logout, mustChangePassword } = useAuth();
  const [initialized, setInitialized] = useState<boolean | null>(null);

  useEffect(() => {
    if (loading) return;
    if (!username) {
      router.replace("/login");
      return;
    }
    if (mustChangePassword) {
      router.replace("/change-password?forced=1");
      return;
    }

    api
      .getSettingsStatus()
      .then((data) => setInitialized(data.initialized))
      .catch(() => setInitialized(false));
  }, [loading, username, mustChangePassword, router]);

  const handleSuccess = () => {
    router.replace("/chat");
  };

  const handleCancel = () => {
    router.replace("/chat");
  };

  const handleForceLogout = async () => {
    await logout();
    router.replace("/login");
  };

  if (loading || initialized === null) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a]">
        <div className="text-gray-400">Loading...</div>
      </div>
    );
  }

  return (
    <SettingsForm
      onSuccess={handleSuccess}
      onCancel={initialized ? handleCancel : undefined}
      onForceLogout={() => {
        void handleForceLogout();
      }}
    />
  );
}
