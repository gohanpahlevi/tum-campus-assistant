# TUM Campus Assistant

A question answering service for TUM students and staff, running on Google Cloud Run at https://tum-chatbot-920516460156.europe-west3.run.app

Built by a team of six for a Generative AI course at TUM School of Management. I led the team and did the deployment work. The application code is the team's.

The team's original repository is at https://github.com/miglios2912/Group-19---Gen-AI. This repository is the version that is deployed, with the container build and the Cloud Run setup added.

## What it does

It answers questions about TUM's campuses, services and procedures from a knowledge base of 270 entries, using Gemini to write the answer.

The part worth looking at is when it asks who you are. Most of these systems open by demanding your role and campus before they will say anything. This one decides per question. "How do I reset my password" is answered immediately. "Where is the mensa" needs a campus, so it asks for a campus and nothing else. Once you have answered, it never asks again in that session.

That logic is in `needs_user_info` in `backend/chatbot_v2.py`. Rules handle most queries and only what falls through reaches the model, which keeps the common case fast and predictable.

## Retrieval

Retrieval is keyword matching with query expansion, scored against the question, answer, category, role and keyword fields of each entry.

An earlier version used ChromaDB with sentence-transformers embeddings and ran semantic, keyword and hybrid search side by side. We replaced all three with one tuned keyword method. The three scoring systems disagreed with each other, the hybrid results were unpredictable, and the vector store cost startup time and memory without retrieving better answers on a corpus this size. `docs/retrieval-design.md` is the write-up from the time, including the specific query that exposed the problem.

This is the right tradeoff for 270 curated entries. It would not be for a large or growing corpus.

## Security

User input is checked for prompt injection before it reaches the knowledge base. Repeat offenders are blacklisted by IP, and the blacklist lives in Firestore rather than in the container, because Cloud Run instances are replaced and anything held in memory is lost.

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

The build runs on Cloud Build, not locally. A local docker build on an Apple Silicon Mac produces an arm64 image and Cloud Run only runs amd64, so the service would fail to start.

```
gcloud builds submit --config cloudbuild.yaml --project <PROJECT_ID>

gcloud run deploy tum-chatbot \
  --image europe-west3-docker.pkg.dev/<PROJECT_ID>/tum-chatbot/tum-chatbot:latest \
  --region europe-west3 --allow-unauthenticated \
  --set-env-vars ENVIRONMENT=production,FIRESTORE_PROJECT_ID=<PROJECT_ID> \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest \
  --memory 2Gi --cpu 2 --port 8080
```

The API key comes from Secret Manager, so it is never in the image, in the deploy command, or in `gcloud run services describe`. Rotating it is a new secret version with no rebuild.

`.gcloudignore` keeps `.env` files out of the build context. The Dockerfile copies `backend/` wholesale, so without it a local `.env` would be baked into a public image.

## Tests

```
pip install pytest
pytest
```

15 tests over the context rules and the retrieval scoring. They run without a network call. The paths that ask the model for a judgement are not covered, and one test pins the boundary where the rules hand over to it.

## Not in this repository

The knowledge base content is TUM's. The campus maps and logo are TUM's. They are here because the application does not run without them, not as something I am licensing on.
