# PROJECT_CONTEXT

## Goal

Content generation workflow for article production, review, and automatic cover-image generation.

## Current state

- Text workflow uses LangGraph plus StepFun `Step Plan`.
- Cover-image workflow is already implemented in the codebase.
- The project now has real image generation enabled instead of mock mode.
- The active runtime env is in `.env`.

## Key runtime facts

- Text provider route: `STEPFUN_API_BASE=https://api.stepfun.com/step_plan/v1`
- Text model: `STEPFUN_MODEL=step-3.5-flash`
- Image provider route: `STEPFUN_IMAGE_API_BASE=https://api.stepfun.com/v1`
- Image model: `STEPFUN_IMAGE_MODEL=step-2x-large`
- Image mock switch: `IMAGE_MOCK=false`
- Vision provider route: `STEPFUN_VISION_API_BASE=https://api.stepfun.com/v1` (OpenAI-compatible chat vision)
- Vision model: `STEPFUN_VISION_MODEL=step-1o-turbo-vision`
- Vision mock switch: `VISION_REVIEW_MOCK=true` (set `false` and provide `STEPFUN_VISION_API_KEY` or a shared StepFun key for real cover visual QA)

## Key files

- `README.md`
- `.env`
- `src/api_v2.py`
- `src/langgraph_v2/settings.py`
- `src/langgraph_v2/engine.py`

## Commands

- Install deps: `pip install -r requirements.txt`
- Run API: `cd src && py -m uvicorn api_v2:app --host 127.0.0.1 --port 8000`
- Health check: `curl http://127.0.0.1:8000/health`

## Constraints

- Keep text on `Step Plan` and images on the normal StepFun image API (`step-2x-large` baseline).
- Cover visual review uses the StepFun vision chat API; do not conflate it with the image generation endpoint.
- Do not switch image generation back to mock unless explicitly required.
- Prefer additive changes around the existing `plan_cover -> generate_cover` flow.

## Handoff rule

Always read `HANDOFF.md` before continuing work on this project.
