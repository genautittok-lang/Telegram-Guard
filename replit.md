# replit.md

## Overview

This is a Mastra-based AI automation platform that enables building agentic workflows with durable execution. The system uses Mastra for AI agents and workflows, with Inngest providing durability and orchestration. It supports time-based (cron) triggers and webhook-based triggers (Telegram, Slack, Linear, etc.) to automate AI-powered tasks.

The core purpose is to create automated AI workflows that can be triggered by external events or schedules, with built-in retry logic, suspend/resume capabilities, and persistent memory.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Framework Stack
- **Mastra Framework**: Core AI agent and workflow orchestration (`@mastra/core`)
- **Inngest**: Durable execution layer for step-by-step workflow orchestration with automatic retries
- **TypeScript/ES Modules**: Modern TypeScript with ESM module system

### Agent Architecture
- Agents are defined in `src/mastra/agents/` using Mastra's `Agent` class
- Agents use OpenAI/OpenRouter models via AI SDK providers
- Memory system supports conversation history, semantic recall, and working memory
- Agents can use tools defined in `src/mastra/tools/`

### Workflow Architecture
- Workflows defined in `src/mastra/workflows/` using `createWorkflow` and `createStep`
- Steps have typed input/output schemas using Zod
- Support for branching, parallel execution, and human-in-the-loop patterns
- Workflows can call agents using `mastra.getAgent()` and `agent.generateLegacy()` (required for Replit Playground UI compatibility)

### Trigger System
- **Time-based triggers**: Use `registerCronTrigger()` in `src/triggers/cronTriggers.ts`, called before Mastra initialization
- **Webhook triggers**: Use `registerApiRoute()` pattern, spread into `apiRoutes` array in `src/mastra/index.ts`
- Existing trigger implementations: Telegram (`telegramTriggers.ts`), Slack (`slackTriggers.ts`), example connector (`exampleConnectorTrigger.ts`)

### Inngest Integration
- Custom Inngest client in `src/mastra/inngest/client.ts`
- `inngestServe` middleware connects Mastra workflows to Inngest
- All workflows are orchestrated step-by-step through Inngest for durability
- Dev server runs on port 3000, Mastra server on port 5000

### Entry Point
- Main Mastra instance exported from `src/mastra/index.ts`
- This file registers all agents, workflows, and API routes
- Critical to preserve Inngest imports: `import { inngest, inngestServe } from "./inngest"`

### Key Design Decisions
1. **generateLegacy over generate**: Replit Playground UI requires `agent.generateLegacy()` for backwards compatibility
2. **Trigger registration timing**: Cron triggers must be called BEFORE Mastra initialization; webhook triggers are spread into apiRoutes array
3. **Workflow input schemas**: Time-based workflows use empty input schema `z.object({})` since they don't receive external input
4. **Storage layer**: Uses PostgreSQL via `@mastra/pg` for shared storage across workflows

## External Dependencies

### AI/LLM Providers
- `@ai-sdk/openai`: OpenAI model integration
- `@openrouter/ai-sdk-provider`: OpenRouter for multi-model access
- `openai`: Direct OpenAI API client

### Orchestration & Durability
- `inngest`: Background workflow execution with durability
- `@mastra/inngest`: Mastra-Inngest integration layer
- `@inngest/realtime`: Real-time workflow monitoring

### Storage & Memory
- `@mastra/pg`: PostgreSQL storage adapter
- `@mastra/libsql`: LibSQL storage adapter (alternative)
- `@mastra/memory`: Agent memory system (conversation history, semantic recall)
- `pg`: PostgreSQL client

### External Service Integrations
- `@slack/web-api`: Slack bot integration
- Telegram Bot API (via custom triggers)
- Linear webhooks (example connector)

### Utilities
- `zod`: Schema validation for workflow steps
- `drizzle-zod`: Drizzle ORM schema integration
- `pino`: Logging via `@mastra/loggers`
- `dotenv`: Environment variable management

### Development
- `mastra`: CLI for dev server (`npm run dev`)
- `tsx`: TypeScript execution
- `prettier`: Code formatting