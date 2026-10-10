---
license: mit
base_model: BAAI/bge-small-en-v1.5
library_name: onnx
pipeline_tag: sentence-similarity
tags:
  - retrieval
  - onnx
  - customer-support
  - rag
---

# Pleiades-Embed

A retrieval encoder fine-tuned for Pleiades, a customer-support assistant that answers from an
organisation's own documents. It is `BAAI/bge-small-en-v1.5` fine-tuned on that organisation's
knowledge base, exported to ONNX with int8 weights so it runs on a CPU in about 30 ms per query
and fits a 512 MB server.

## What it was trained on

Customer-style questions written for each passage of the demo knowledge base (Nimbus Networks, a
fictional internet provider: billing FAQ, router manual, returns policy, plan catalog, resolved
tickets), the way customers describe a problem rather than the way the document names it. A
question was kept only if every figure in its answer appears in its passage, and anything close
to a held-out evaluation question was removed. 169 training pairs, 29 validation pairs, split
by section so validation only asks about passages the model never saw.

Training used in-batch negatives (multiple negatives ranking loss) for 8 epochs, with mean
pooling and a 256-token limit, the same pooling and limit used at inference.

## Results

| Encoder | Recall@6, unseen sections | MRR | Recall@6, held-out questions |
|---|---|---|---|
| all-MiniLM-L6-v2 | 79.3% | 0.675 | 80.0% |
| bge-small-en-v1.5 | 82.8% | 0.684 | 80.0% |
| **Pleiades-Embed** | **93.1%** | **0.724** | **86.7%** |

The model was chosen on the validation split; the held-out questions were read once, afterwards.
Inside the full Pleiades pipeline (keyword search and query expansion added) it retrieves the
right passage for every held-out question, and with a 4B model running entirely offline it raises
answer accuracy from 76.5% to 82.4%.

## Use

The `onnx/` folder is laid out the way ChromaDB's ONNX embedding function expects. Mean-pool the
last hidden state over the attention mask and L2-normalise.

## Limits

It is specialised to one knowledge base and was measured on small sets: 29 validation questions
and 15 held-out questions, where one question is worth several points. Treat it as a demonstration
of adapting retrieval to a tenant's documents, not as a general-purpose encoder.
