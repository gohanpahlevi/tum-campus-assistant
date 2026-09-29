# TUM Campus Assistant

A question answering service for TUM students and staff, running on Google Cloud Run at https://tum-chatbot-920516460156.europe-west3.run.app

Built for a Generative AI course at TUM School of Management by a team of six. I worked on the backend and took the project from a course prototype to a running service. That meant the production architecture, the container build, the Cloud Run deployment, and moving the security blacklist out of memory and into Firestore.

The team's submission repository is at https://github.com/miglios2912/Group-19---Gen-AI. This repository is the version that runs in production.

## What it does

It answers questions about TUM's campuses, services and procedures from a knowledge base of 270 entries, using Gemini to write the answer.

Answers depend on who is asking. A student and an employee get different parking rules, and each campus has its own mensa. Most chatbots deal with this by asking for your role and campus before the first question. This one asks only when the question needs it. "How do I reset my password" is the same answer for everyone, so it just answers. "Where is the mensa" depends on the campus, so it asks for the campus and nothing more. It remembers what you said for the rest of the session.

That decision is made in `needs_user_info` in `backend/chatbot_v2.py`. A set of rules covers most questions, and only the ones the rules cannot settle go to the model. So most questions never wait for a model call.

## Retrieval

Retrieval is keyword matching with query expansion, scored against the question, answer, category, role and keyword fields of each entry.

An earlier version used ChromaDB with sentence-transformers embeddings and ran semantic, keyword and hybrid search side by side. We replaced all three with one tuned keyword method. The three scores were on different scales, so the combined ranking was hard to predict, and the vector store cost startup time and memory without finding better answers in 270 entries. `docs/retrieval-design.md` is the write-up from the time, including the query that exposed the problem.

Keyword matching works here because every entry is written and tagged by hand, so the words in a question are usually the words in the entry. That stops being true once a knowledge base grows and many people write for it. At that point embeddings start to pay for themselves.

## Security

User input is checked for prompt injection before it reaches the knowledge base. Repeat offenders are blacklisted by IP, and the blacklist lives in Firestore, not in the container, because Cloud Run replaces instances and anything held in memory is lost with them.

## Layout

```
backend/     Flask API, retrieval, security, session handling
frontend/    React interface, built by Vite
Dockerfile   one container, Flask serves the built frontend
cloudbuild.yaml
tests/
docs/
```

## Running it locally

```
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY=your_key
python wsgi.py
```

```
cd frontend
npm install
npm run dev
```

## Deploying

The build runs on Cloud Build, not locally. A container image is compiled for one processor architecture. An Apple Silicon Mac builds arm64, Cloud Run runs on amd64 machines, and an arm64 image cannot execute there. The container exits the moment it starts, so the deploy fails.

```
gcloud builds submit --config cloudbuild.yaml --project <PROJECT_ID>

gcloud run deploy tum-chatbot \
  --image europe-west3-docker.pkg.dev/<PROJECT_ID>/tum-chatbot/tum-chatbot:latest \
  --region europe-west3 --allow-unauthenticated \
  --set-env-vars ENVIRONMENT=production,FIRESTORE_PROJECT_ID=<PROJECT_ID> \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest \
  --memory 2Gi --cpu 2 --port 8080
```

The API key comes from Secret Manager. It is not in the image, not in the deploy command and not in `gcloud run services describe`. Rotating it means adding a new secret version, with no rebuild.

`.gcloudignore` keeps `.env` files out of the build context. The Dockerfile copies `backend/` wholesale, so without it a local `.env` would be baked into a public image.

## Tests

```
pip install -r requirements-dev.txt
pytest
```

32 tests covering the context rules, the retrieval scoring, the response formatting and the flow through `generate_response`. None of them call the network. Gemini is stubbed, so what is tested is the routing around the model call and not the text it writes. That includes the point where the rules give up and hand the question over, the question being held while the user is asked for a campus, and the answer coming back once they reply.

## TUM's material

The knowledge base content, the campus maps and the logo belong to TUM, not to me. They are in this repository because the application does not run without them.
