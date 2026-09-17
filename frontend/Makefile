ENV_FILE := .env

# -------------------
# Local dev
# -------------------

.PHONY: install
install:
	npm install

.PHONY: dev
dev:
	npm run dev

# -------------------
# Deploy
# -------------------

# point the frontend at a backend URL (e.g. an ngrok tunnel or Cloud Run URL)
# usage: make set-api-url URL=https://xxxx.ngrok-free.dev
.PHONY: set-api-url
set-api-url:
	@test -n "$(URL)" || (echo "Usage: make set-api-url URL=https://your-backend-url"; exit 1)
	@sed -i.bak "s|^VITE_API_URL=.*|VITE_API_URL=$(URL)|" $(ENV_FILE) && rm -f $(ENV_FILE).bak
	@echo "VITE_API_URL set to $(URL)"

.PHONY: build
build:
	npm run build

# build + publish to Firebase Hosting using whatever VITE_API_URL is
# currently set in .env
.PHONY: deploy
deploy: build
	firebase deploy --only hosting

# one-shot: point at a backend URL, then build + deploy
# usage: make deploy-tunnel URL=https://xxxx.ngrok-free.dev
.PHONY: deploy-tunnel
deploy-tunnel:
	@test -n "$(URL)" || (echo "Usage: make deploy-tunnel URL=https://your-backend-url"; exit 1)
	$(MAKE) set-api-url URL=$(URL)
	$(MAKE) deploy
