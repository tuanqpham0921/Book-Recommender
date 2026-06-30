# 1. Update .env with your production backend URL
VITE_API_URL=https://your-cloud-run-url.a.run.app

# 2. Build
npm run build

# 3. Deploy
firebase deploy --only hosting:book-rec --project tuanqpham0921