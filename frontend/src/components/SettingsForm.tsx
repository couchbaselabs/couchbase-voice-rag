"use client";

import { useEffect, useState } from "react";
import { useForm, type FieldError } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import * as api from "@/lib/api";
import { isApiError, toastApiError } from "@/lib/errors";

const settingsSchema = z
  .object({
    cb_connection_string: z.string().min(1, "Connection string is required"),
    cb_username: z.string().min(1, "Username is required"),
    cb_password: z.string().min(1, "Password is required"),
    cb_bucket: z.string().min(1, "Bucket name is required"),
    cb_scope: z.string().min(1, "Scope name is required"),
    cb_collection: z.string().min(1, "Collection name is required"),
    cb_search_index: z.string().min(1, "Search index name is required"),
    embedding_method: z.enum(["python", "capella"]),
    azure_openai_endpoint: z
      .string()
      .min(1, "Azure OpenAI endpoint is required")
      .url("Must be a valid URL"),
    openai_api_key: z.string().min(1, "Azure OpenAI API key is required"),
    openai_realtime_model: z.string().min(1, "Realtime deployment is required"),
    openai_embedding_model: z.string().min(1, "Embedding deployment is required"),
    capella_api_key_id: z.string(),
    capella_api_key_token: z.string(),
    capella_workflow_name: z.string(),
    deepgram_api_key: z.string(),
    tavily_api_key: z.string(),
    web_search_enabled: z.boolean(),
  })
  .superRefine((data, ctx) => {
    if (data.embedding_method === "capella") {
      if (!data.capella_api_key_id) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["capella_api_key_id"],
          message: "Capella API Key ID is required for Capella embedding method",
        });
      }
      if (!data.capella_api_key_token) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["capella_api_key_token"],
          message: "Capella API Key Token is required for Capella embedding method",
        });
      }
    }
    if (data.web_search_enabled && !data.tavily_api_key) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["tavily_api_key"],
        message: "Tavily API key is required when web search fallback is enabled",
      });
    }
  });

type SettingsFormValues = z.infer<typeof settingsSchema>;

type StringFieldKey = Exclude<keyof SettingsFormValues, "web_search_enabled" | "embedding_method">;

interface SettingsFormProps {
  onSuccess: () => void;
  onCancel?: (() => void) | undefined;
  onForceLogout?: (() => void) | undefined;
}

interface FieldDef {
  key: StringFieldKey;
  label: string;
  placeholder: string;
  isSecret: boolean;
}

const CB_FIELDS: FieldDef[] = [
  {
    key: "cb_connection_string",
    label: "Connection String",
    placeholder: "couchbase://localhost or couchbases://cb.xxx.cloud.couchbase.com",
    isSecret: false,
  },
  { key: "cb_username", label: "Username", placeholder: "", isSecret: false },
  { key: "cb_password", label: "Password", placeholder: "", isSecret: true },
  { key: "cb_bucket", label: "Bucket Name", placeholder: "realtime-rag", isSecret: false },
  { key: "cb_scope", label: "Scope Name", placeholder: "_default", isSecret: false },
  {
    key: "cb_collection",
    label: "Collection Name",
    placeholder: "documents_local",
    isSecret: false,
  },
  {
    key: "cb_search_index",
    label: "Search Index Name",
    placeholder: "vector-search-index-local",
    isSecret: false,
  },
];

const OPENAI_FIELDS: FieldDef[] = [
  {
    key: "azure_openai_endpoint",
    label: "Azure OpenAI Endpoint",
    placeholder: "https://your-resource.openai.azure.com",
    isSecret: false,
  },
  { key: "openai_api_key", label: "API Key", placeholder: "", isSecret: true },
  {
    key: "openai_realtime_model",
    label: "Realtime Deployment",
    placeholder: "gpt-4o-mini-realtime-preview",
    isSecret: false,
  },
  {
    key: "openai_embedding_model",
    label: "Embedding Deployment",
    placeholder: "text-embedding-3-small",
    isSecret: false,
  },
];

const CAPELLA_FIELDS: FieldDef[] = [
  { key: "capella_api_key_id", label: "API Key ID", placeholder: "", isSecret: true },
  { key: "capella_api_key_token", label: "API Key Token", placeholder: "", isSecret: true },
  {
    key: "capella_workflow_name",
    label: "AI Workflow Name",
    placeholder: "realtime_rag_vectorization",
    isSecret: false,
  },
];

const DEEPGRAM_FIELD: FieldDef = {
  key: "deepgram_api_key",
  label: "Deepgram API Key (required for voice STT)",
  placeholder: "",
  isSecret: true,
};

const TAVILY_FIELD: FieldDef = {
  key: "tavily_api_key",
  label: "Tavily API Key (web search fallback)",
  placeholder: "",
  isSecret: true,
};

function defaultCollection(method: string): string {
  return method === "python" ? "documents_local" : "documents_capella";
}

function defaultSearchIndex(method: string): string {
  return method === "python" ? "vector-search-index-local" : "vector-search-index-capella";
}

const EMBEDDING_OPTIONS = [
  {
    value: "capella",
    label: "Capella AI Services",
    description: "Capella AI Services workflow generates embeddings (documents_capella).",
  },
  {
    value: "python",
    label: "Python (local)",
    description: "Backend generates embeddings via Azure OpenAI (documents_local).",
  },
] as const;

const EMPTY_DEFAULTS: SettingsFormValues = {
  cb_connection_string: "",
  cb_username: "",
  cb_password: "",
  cb_bucket: "",
  cb_scope: "_default",
  cb_collection: "",
  cb_search_index: "",
  embedding_method: "capella",
  azure_openai_endpoint: "",
  openai_api_key: "",
  openai_realtime_model: "",
  openai_embedding_model: "",
  capella_api_key_id: "",
  capella_api_key_token: "",
  capella_workflow_name: "realtime_rag_vectorization",
  deepgram_api_key: "",
  tavily_api_key: "",
  web_search_enabled: false,
};

const STAGE_LABELS: Record<string, string> = {
  idle: "Connect & Initialize",
  applying: "Applying settings...",
  capella_user: "Provisioning Capella user...",
  capella_bucket: "Provisioning Capella bucket...",
  connecting: "Connecting to Couchbase...",
  creating_bucket: "Creating bucket...",
  creating_collections: "Creating collections...",
  creating_indexes: "Creating indexes...",
  building_search_index: "Building search index...",
  saving: "Saving configuration...",
  done: "Done!",
  error: "Failed",
};

export default function SettingsForm({ onSuccess, onCancel, onForceLogout }: SettingsFormProps) {
  const [secretShown, setSecretShown] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [stage, setStage] = useState<string>("idle");
  const [forceLogoutStatus, setForceLogoutStatus] = useState<"idle" | "loading">("idle");

  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    getValues,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<SettingsFormValues>({
    resolver: zodResolver(settingsSchema),
    defaultValues: EMPTY_DEFAULTS,
    mode: "onSubmit",
    reValidateMode: "onChange",
  });

  useEffect(() => {
    api
      .getSettings()
      .then((data) => {
        const rawMethod = data.settings.embedding_method ?? "capella";
        const method: "python" | "capella" = rawMethod === "python" ? "python" : "capella";
        reset({
          cb_connection_string: data.settings.cb_connection_string ?? "",
          cb_username: data.settings.cb_username ?? "",
          cb_password: data.settings.cb_password ?? "",
          cb_bucket: data.settings.cb_bucket ?? "",
          cb_scope: data.settings.cb_scope ?? "_default",
          cb_collection: data.settings.cb_collection || defaultCollection(method),
          cb_search_index: data.settings.cb_search_index || defaultSearchIndex(method),
          embedding_method: method,
          azure_openai_endpoint: data.settings.azure_openai_endpoint ?? "",
          openai_api_key: data.settings.openai_api_key ?? "",
          openai_realtime_model: data.settings.openai_realtime_model ?? "",
          openai_embedding_model: data.settings.openai_embedding_model ?? "",
          capella_api_key_id: data.settings.capella_api_key_id ?? "",
          capella_api_key_token: data.settings.capella_api_key_token ?? "",
          capella_workflow_name:
            data.settings.capella_workflow_name || "realtime_rag_vectorization",
          deepgram_api_key: data.settings.deepgram_api_key ?? "",
          tavily_api_key: data.settings.tavily_api_key ?? "",
          web_search_enabled: Boolean(data.settings.web_search_enabled),
        });
      })
      .catch((err) => {
        console.error("Failed to load settings:", err);
      })
      .finally(() => setLoading(false));
  }, [reset]);

  const method = watch("embedding_method");
  const webSearchEnabled = watch("web_search_enabled");
  const capellaDisabled = method !== "capella";
  const tavilyDisabled = !webSearchEnabled;

  useEffect(() => {
    // Auto-fill collection / search-index when method changes and the field is empty.
    // Intentionally only re-runs on method change; tracking the current values would
    // re-fire on every keystroke and clobber user edits.
    if (!getValues("cb_collection")) {
      setValue("cb_collection", defaultCollection(method), { shouldValidate: false });
    }
    if (!getValues("cb_search_index")) {
      setValue("cb_search_index", defaultSearchIndex(method), { shouldValidate: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [method]);

  const toggleSecretShown = (key: string) => {
    setSecretShown((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const onSubmit = async (data: SettingsFormValues) => {
    setStage("applying");
    const pollHandle = window.setInterval(() => {
      void api
        .getSettingsProgress()
        .then((p) => setStage(p.stage))
        .catch(() => {
          /* polling failures are non-fatal; the post itself drives the outcome */
        });
    }, 500);
    try {
      await api.saveSettings(data);
      onSuccess();
    } catch (err) {
      if (isApiError(err) && err.status === 400) {
        const suffix = err.requestId ? ` (id: ${err.requestId})` : "";
        setError("root", { type: "server", message: err.detail + suffix });
      } else {
        toastApiError(err, "Failed to save settings.");
      }
    } finally {
      window.clearInterval(pollHandle);
      setStage("idle");
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a]">
        <div className="text-gray-400">Loading settings...</div>
      </div>
    );
  }

  const renderField = (field: FieldDef, disabled = false) => {
    const shown = secretShown[field.key] ?? false;
    const fieldError = errors[field.key] as FieldError | undefined;
    return (
      <div key={field.key}>
        <label
          htmlFor={field.key}
          className={`mb-1 block text-sm font-medium ${disabled ? "text-gray-500" : "text-gray-300"}`}
        >
          {field.label}
        </label>
        <div className="relative">
          <input
            id={field.key}
            type={field.isSecret && !shown ? "password" : "text"}
            placeholder={field.placeholder}
            readOnly={disabled}
            aria-disabled={disabled}
            {...register(field.key)}
            className={`w-full rounded-md border border-gray-600 px-3 py-2 text-white placeholder-gray-500 focus:border-transparent focus:ring-2 focus:ring-red-500 focus:outline-none ${
              disabled ? "cursor-not-allowed bg-gray-900 text-gray-500" : "bg-gray-800"
            }`}
          />

          {field.isSecret && (
            <button
              type="button"
              onClick={() => toggleSecretShown(field.key)}
              aria-label={shown ? "Hide value" : "Show value"}
              aria-pressed={shown}
              className="absolute top-1/2 right-2 -translate-y-1/2 text-gray-400 hover:text-gray-300"
            >
              {shown ? (
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  aria-hidden="true"
                  className="h-5 w-5"
                >
                  <path
                    fillRule="evenodd"
                    d="M3.28 2.22a.75.75 0 00-1.06 1.06l14.5 14.5a.75.75 0 101.06-1.06l-1.745-1.745a10.029 10.029 0 003.3-4.38 1.651 1.651 0 000-1.185A10.004 10.004 0 009.999 3a9.956 9.956 0 00-4.744 1.194L3.28 2.22zM7.752 6.69l1.092 1.092a2.5 2.5 0 013.374 3.373l1.092 1.092a4 4 0 00-5.558-5.558z"
                    clipRule="evenodd"
                  />
                  <path d="M10.748 13.93l2.523 2.523a9.987 9.987 0 01-3.27.547c-4.258 0-7.894-2.66-9.337-6.41a1.651 1.651 0 010-1.186A10.007 10.007 0 012.839 6.02L6.07 9.252a4 4 0 004.678 4.678z" />
                </svg>
              ) : (
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  aria-hidden="true"
                  className="h-5 w-5"
                >
                  <path d="M10 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5z" />
                  <path
                    fillRule="evenodd"
                    d="M.664 10.59a1.651 1.651 0 010-1.186A10.004 10.004 0 0110 3c4.257 0 7.893 2.66 9.336 6.41.147.381.146.804 0 1.186A10.004 10.004 0 0110 17c-4.257 0-7.893-2.66-9.336-6.41zM14 10a4 4 0 11-8 0 4 4 0 018 0z"
                    clipRule="evenodd"
                  />
                </svg>
              )}
            </button>
          )}
        </div>
        {fieldError?.message && (
          <p className="mt-1 text-xs text-red-400" role="alert">
            {fieldError.message}
          </p>
        )}
      </div>
    );
  };

  const rootError = errors.root?.message;

  return (
    <div className="flex min-h-screen items-center justify-center overflow-y-auto bg-[#0a0a0a] p-4">
      <div className="my-auto w-full max-w-2xl rounded-lg border border-gray-700 bg-[#1a1a2e] p-8 shadow-lg">
        <h1 className="mb-2 text-xl font-bold text-gray-100">Settings</h1>
        <p className="mb-4 text-sm text-gray-400">
          Configure cluster connection, Azure OpenAI deployment, and optional integrations. Secrets
          are encrypted on disk.
        </p>

        <div className="mb-6 rounded-md border border-blue-800 bg-blue-900/30 px-4 py-3">
          <p className="text-sm text-blue-300">
            Click <strong>Connect &amp; Initialize</strong> to apply these settings. In Capella mode
            the demo creates the DB user, bucket, scope, collection, and search index via the
            Management API + SDK; in Docker mode the bundled cluster is bootstrapped via REST + SDK.
            Existing resources are reused idempotently.
          </p>
        </div>

        <form
          onSubmit={(e) => {
            void handleSubmit(onSubmit)(e);
          }}
          className="space-y-5"
        >
          <div>
            <h2 className="mb-3 text-sm font-semibold text-gray-200">Embedding Method</h2>
            <div className="space-y-2">
              {EMBEDDING_OPTIONS.map((option) => {
                const selected = method === option.value;
                return (
                  <label
                    key={option.value}
                    className={`flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors ${
                      selected
                        ? "border-red-500 bg-red-900/20"
                        : "border-gray-600 bg-gray-800 hover:bg-gray-700"
                    }`}
                  >
                    <input
                      type="radio"
                      value={option.value}
                      {...register("embedding_method")}
                      className="mt-1 accent-red-500"
                    />
                    <div>
                      <div className="text-sm font-medium text-gray-200">{option.label}</div>
                      <div className="text-xs text-gray-400">{option.description}</div>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>

          <div className="space-y-3">
            <h2 className="text-sm font-semibold text-gray-200">Couchbase Cluster</h2>
            {CB_FIELDS.map((field) => renderField(field))}
          </div>

          <div className="space-y-3">
            <h2 className="text-sm font-semibold text-gray-200">Azure OpenAI</h2>
            {OPENAI_FIELDS.map((field) => renderField(field))}
          </div>

          <div className={`space-y-3 ${capellaDisabled ? "opacity-60" : ""}`}>
            <h2 className="text-sm font-semibold text-gray-200">
              Capella AI Services{" "}
              <span className="text-xs font-normal text-gray-400">
                (only when Embedding Method = Capella)
              </span>
            </h2>
            {CAPELLA_FIELDS.map((field) => renderField(field, capellaDisabled))}
          </div>

          <div className="space-y-3">
            <h2 className="text-sm font-semibold text-gray-200">Integrations</h2>

            {renderField(DEEPGRAM_FIELD)}

            <label className="flex cursor-pointer items-start gap-3 rounded-md border border-gray-600 bg-gray-800/50 p-3">
              <input
                type="checkbox"
                role="switch"
                {...register("web_search_enabled")}
                className="mt-1 h-4 w-4 accent-red-500"
                aria-label="Web search fallback"
              />
              <div>
                <div className="text-sm font-medium text-gray-200">Web search fallback</div>
                <div className="text-xs text-gray-400">
                  When the knowledge base has no relevant results, let the assistant search the web
                  via Tavily. Effective only when a Tavily API key is set below.
                </div>
              </div>
            </label>

            <div className={tavilyDisabled ? "opacity-60" : ""}>
              {renderField(TAVILY_FIELD, tavilyDisabled)}
            </div>
          </div>

          {rootError && (
            <div className="rounded-md border border-red-800 bg-red-900/30 px-4 py-3">
              <p className="text-sm text-red-400">{rootError}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-red-600 px-4 py-2 text-white transition-colors hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isSubmitting && (
              <svg
                className="h-5 w-5 animate-spin"
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                aria-hidden="true"
              >
                <circle
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                  className="opacity-25"
                />
                <path
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  className="opacity-75"
                />
              </svg>
            )}
            <span>
              {isSubmitting
                ? (STAGE_LABELS[stage] ?? "Connecting to Couchbase...")
                : "Connect & Initialize"}
            </span>
          </button>

          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              className="w-full rounded-md bg-gray-700 px-4 py-2 text-gray-300 transition-colors hover:bg-gray-600"
            >
              Cancel
            </button>
          )}
        </form>

        {onForceLogout && (
          <div className="mt-8 border-t border-gray-700 pt-6">
            <h2 className="mb-3 text-sm font-medium text-gray-400">Session Management</h2>
            <button
              type="button"
              disabled={forceLogoutStatus === "loading"}
              onClick={() => {
                void (async () => {
                  setForceLogoutStatus("loading");
                  try {
                    await api.forceLogout();
                    onForceLogout();
                  } catch {
                    setForceLogoutStatus("idle");
                  }
                })();
              }}
              className="w-full rounded-md border border-red-800 bg-red-900/50 px-4 py-2 text-sm text-red-300 transition-colors hover:bg-red-900/70 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {forceLogoutStatus === "loading" ? "Processing..." : "Force Logout All Sessions"}
            </button>
            <p className="mt-2 text-xs text-gray-400">
              Invalidates all active tokens. Every user will be logged out immediately.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
