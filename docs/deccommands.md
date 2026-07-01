🐳 1. DOCKER COMMANDS (CORE SYSTEM)
▶ Start development environment
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
⛔ Stop development environment
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
🔁 Restart dev system
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
📊 Check running containers
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps
📜 View logs
docker compose logs -f api
docker compose logs -f worker
🧹 Clean system (careful)
docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v
🧠 Rebuild everything
docker compose -f docker-compose.yml -f docker-compose.dev.yml build --no-cache
🧪 Health check
curl http://localhost:8000/health
🚀 2. PRODUCTION COMMANDS
▶ Start production
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production up -d
⛔ Stop production
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
📊 Production status
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
🧱 3. ALEMBIC (DATABASE MIGRATIONS)
▶ Create migration
alembic revision --autogenerate -m "description"
▶ Apply migrations
alembic upgrade head
⬅ Rollback 1 step
alembic downgrade -1
📊 Migration status
alembic current
📜 Migration history
alembic history
🧪 4. BACKEND TESTING
▶ Run all tests
pytest backend/tests -q
▶ Run specific test
pytest backend/tests/test_file.py -q
🎨 5. FRONTEND COMMANDS
▶ Run dev frontend
cd frontend
npm run dev
▶ Build frontend
npm run build
▶ Type check
tsc -b
🧠 6. SYSTEM DEBUG COMMANDS
▶ Check API health
curl http://localhost:8000/health
▶ Check container logs (real-time debugging)
docker logs -f yara-api-1
docker logs -f yara-worker-1
🧹 7. CLEAN RESET (SAFE DEV RESET)
Reset database + containers
docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
📌 8. IMPORTANT RULES (VERY IMPORTANT)
❌ NEVER run production without explicit compose file
❌ NEVER assume override behavior
❌ ALWAYS verify with:
docker compose ps
curl /health
