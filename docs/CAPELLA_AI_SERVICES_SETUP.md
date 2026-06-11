# Capella AI Services Setup Guide

This guide covers the post-deployment steps for configuring Couchbase Capella AI Services with the Couchbase RAG application deployed at `couchbase-rag.ecoplanty.com`.

## Prerequisites

- Application deployed and accessible
- Couchbase Capella cluster with **AI Services enabled** (Server 8.0+, Search + Eventing services)

---

## Step 1: Set Up Custom Domain (DNS)

1. Go to your DNS provider and add a CNAME record:

   ```
   couchbase-rag.ecoplanty.com  CNAME  <FRONTEND_FQDN from deployment output>
   ```

2. Bind the hostname in Azure (commands are printed at the end of `scripts/deploy-couchbase-rag.sh`):

   ```bash
   az containerapp hostname add \
     --name couchbase-rag-frontend \
     --resource-group couchbase-rag-rg \
     --hostname couchbase-rag.ecoplanty.com

   az containerapp hostname bind \
     --name couchbase-rag-frontend \
     --resource-group couchbase-rag-rg \
     --hostname couchbase-rag.ecoplanty.com \
     --environment couchbase-rag-env \
     --validation-method CNAME
   ```

3. Wait a few minutes for TLS certificate provisioning (automatic).

---

## Step 2: Configure Couchbase Connection

1. Open `https://couchbase-rag.ecoplanty.com` and log in (default: `admin` / `Qwer1234!`).
2. The **Couchbase Cluster Settings** form will appear automatically.
3. Fill in your Couchbase Capella connection details:
   - **Connection String**: `couchbases://cb.xxx.cloud.couchbase.com`
   - **Username**: Your database user
   - **Password**: Your database password
   - **Bucket Name**: Your bucket name (must be created beforehand in Capella)
   - Leave Scope, Collection, and Search Index as defaults
4. Click **Connect & Initialize**.

---

## Step 3: Create a Capella AI Services Workflow

This is the key step. You configure a workflow in the Capella UI that watches the `raw_documents` collection and automatically chunks + embeds documents into the `documents` collection.

**No API key is needed** -- the workflow runs inside Capella using Eventing, triggered automatically when documents are inserted.

### 3.1 Open AI Services in Capella Console

1. Go to [Capella Cloud Console](https://cloud.couchbase.com).
2. Navigate to your cluster.
3. Go to **AI Services** > **Workflows**.

### 3.2 Create a Vectorization Workflow

1. Click **Create Workflow**.
2. Select workflow type: **Data from Capella**.
3. Configure the source:

   | Setting | Value |
   |---------|-------|
   | **Source Cluster** | Your operational cluster |
   | **Source Bucket** | Your bucket (e.g., `rag_sehyun`) |
   | **Source Scope** | `_default` |
   | **Source Collection** | `raw_documents` |
   | **Source Field** | `All source fields` (or `text` if visible) |

4. Configure the target:

   | Setting | Value |
   |---------|-------|
   | **Target Cluster** | Same cluster |
   | **Target Bucket** | Same bucket |
   | **Target Scope** | `_default` |
   | **Target Collection** | `documents` |

5. Configure embedding:

   | Setting | Value |
   |---------|-------|
   | **Embedding Provider** | OpenAI |
   | **Embedding Model** | text-embedding-3-small |
   | **OpenAI API Key** | Your OpenAI API key |

6. Configure chunking:

   | Setting | Value |
   |---------|-------|
   | **Chunking Strategy** | Recursive |
   | **Max Chunk Size** | 500 tokens |
   | **Chunk Overlap** | 50 tokens |

7. Save and activate the workflow.

---

## Step 4: Test the Pipeline

### Upload a Document

1. Click the **Upload** button in the sidebar.
2. Select a PDF file.
3. The app will:
   - Extract text from the PDF
   - Store raw text in the `raw_documents` collection
   - Wait for Capella Eventing to automatically process it
   - Poll the `documents` collection until chunks appear
   - Report the number of chunks created

### Verify in Capella Console

1. Go to your cluster in Capella.
2. Check the `documents` collection -- it should contain chunked documents with embeddings.
3. Check the `raw_documents` collection -- it should be empty (cleaned up after processing).

### Test RAG Query

1. Type a question in the chat or use voice input.
2. The app will:
   - Generate a query embedding (using the same text-embedding-3-small model)
   - Search the `documents` collection via vector search
   - Return relevant context to the LLM for response generation

---

## Architecture Overview

```
PDF Upload
    |
    v
Python Backend -----> raw_documents collection (staging)
(extract text)                |
                              | Capella Eventing (auto-triggered)
                              v
                     Capella AI Services Workflow
                     (chunk + embed with OpenAI)
                              |
                              v
                     documents collection (chunks + vectors)
                              |
                              v
                     Vector Search Index
                     (RAG query results)
```

**How it works**:
1. The backend extracts text from the uploaded PDF and inserts it into `raw_documents`.
2. Capella's Eventing service detects the new document and triggers the AI Services workflow.
3. The workflow chunks the text and generates embeddings using OpenAI.
4. The results are written to the `documents` collection with vector embeddings.
5. The backend polls `documents` until chunks appear, then returns the result.

---

## Troubleshooting

### Upload Times Out (No Chunks Produced)

- Verify the workflow is **active** in the Capella console (AI Services > Workflows).
- Check that the source collection is `raw_documents` and target is `documents`.
- Ensure the Eventing service is running on your cluster.
- Check the workflow logs in the Capella console for errors.

### Vector Search Returns No Results

- Confirm documents exist in the `documents` collection with `embedding` fields.
- Check that the vector search index is created (the app auto-creates it on Connect & Initialize).
- Verify the embedding dimension matches (1536 for text-embedding-3-small).
- If Capella uses a different field name for embeddings, the search index may need adjustment.

### Fallback to Python Pipeline

If the Capella AI Services workflow is not configured, the app automatically falls back to the built-in Python pipeline (chunking with LangChain + embedding with Azure OpenAI). This happens transparently -- just upload PDFs as usual.
