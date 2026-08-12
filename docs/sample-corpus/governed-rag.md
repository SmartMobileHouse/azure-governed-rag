# What "governed RAG" means

Retrieval-augmented generation (RAG) grounds a language model's answers in a
specific set of documents by retrieving relevant passages and passing them to
the model as context. A governed RAG system adds the controls an enterprise
needs before that pattern can touch real data.

Governance in this template rests on five ideas. First, identity: every call to
a model, a safety service, or the database is made with a managed identity, so
there are no API keys or connection strings to leak. Second, safety on the way
in and the way out: user input and retrieved passages are screened for prompt
injection, and generated answers are checked for groundedness before they are
returned. Third, a human approval gate for low-confidence or sensitive turns,
while hard safety violations are blocked outright and cannot be overridden.
Fourth, an audit trail that records what was asked, what was retrieved, and what
was decided, without storing raw personal data. Fifth, portability: the system
runs in your own cloud on open, standards-based foundations, so you keep the
code and can move it.

The goal is not a smarter chatbot. It is a retrieval system a risk officer and
an auditor can both live with.
