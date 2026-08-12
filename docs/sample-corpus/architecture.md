# Architecture of the azure-governed-rag template

The application runs as a container on Azure Container Apps, fronted by the
platform's built-in Microsoft Entra authentication, so unauthenticated requests
are rejected before they reach the code. The container runs as a user-assigned
managed identity, which is the single identity used to reach every other
service.

Language capabilities come from Azure AI Foundry: a chat model generates
answers and an embedding model turns text into vectors. Azure AI Content Safety
provides prompt-injection shields and output screening, and Azure AI Language
provides personal-data detection. All three are reached with the managed
identity and Entra tokens rather than keys.

State lives in a single Azure Database for PostgreSQL Flexible Server. The
pgvector extension stores document embeddings for retrieval, and the same server
holds the LangGraph checkpointer, which persists the state of each conversation
so a run can survive a restart and pause for human approval. The database uses
Entra-only authentication; the application fetches a short-lived access token
instead of a password.

Orchestration is handled by LangGraph. The retrieval-augmented flow is expressed
as a graph whose nodes screen input, retrieve context, generate an answer, check
groundedness, and optionally pause for approval. Because the flow is an explicit
graph with persisted state, every step is inspectable, which is what makes the
system auditable.
