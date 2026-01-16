# replit.md

## Overview

This is a Telegram bot application for phone number verification through Telegram. The bot allows users to authenticate their Telegram accounts and check if phone numbers are registered on Telegram. It's built using Python with the python-telegram-bot library for bot interactions and Telethon for Telegram client operations. The application stores user sessions in a PostgreSQL database.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Bot Framework
- **Primary Library**: python-telegram-bot for handling bot commands and callbacks
- **Client Library**: Telethon for Telegram MTProto API operations (checking phone numbers, managing contacts)
- **Rationale**: python-telegram-bot provides simple bot interaction handling while Telethon enables advanced Telegram client features like contact management and user lookup

### State Management
- **Approach**: In-memory dictionaries (`user_states`, `user_data`) for tracking user conversation states
- **Purpose**: Managing multi-step authentication flows (phone number → API credentials → SMS code)
- **Trade-off**: Simple implementation but state is lost on restart; database stores persistent session data

### Database Layer
- **Database**: PostgreSQL with psycopg2-binary driver
- **Connection Pooling**: SimpleConnectionPool (1-10 connections) for efficient database access
- **Schema**: Sessions table for storing authenticated Telegram sessions
- **Rationale**: PostgreSQL provides reliable persistent storage for user session data

### Authentication Flow
The bot implements a multi-step authentication process:
1. User provides phone number
2. User provides API ID and API Hash (from my.telegram.org)
3. Telegram sends SMS code
4. User enters verification code
5. Session is stored for future use

### HTTP Server
- Basic HTTP server running in a separate thread (likely for health checks or webhooks)
- Keeps the application alive on hosting platforms

## External Dependencies

### Telegram APIs
- **Bot API**: Via python-telegram-bot for user interactions
- **MTProto API**: Via Telethon for client-level operations (requires API ID and API Hash per user)

### Database
- **PostgreSQL**: Connected via `DATABASE_URL` environment variable
- **Driver**: psycopg2-binary for database operations

### Environment Variables Required
- `TELEGRAM_BOT_TOKEN`: Bot token from @BotFather
- `DATABASE_URL`: PostgreSQL connection string

### Python Packages
- python-telegram-bot: Bot framework
- telethon: Telegram client library
- psycopg2-binary: PostgreSQL adapter
- python-dotenv: Environment variable loading
- qrcode/pillow: QR code generation (for potential QR login feature)

### Note on Replit Integration Files
The `.replit_integration_files/` directory contains pre-built components for AI integrations (chat, audio, image) using OpenAI-compatible APIs. These are not currently integrated with the main bot application but are available for future AI feature expansion.