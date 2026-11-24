# RainCheck frontend

```powershell
npm install
npm run dev
npm test
npx playwright test
```

Opens at http://127.0.0.1:5173. The API address is `VITE_API_URL`, default `http://127.0.0.1:8000`. Start the API first. Replaying a season also needs the local chain (`scripts/dev.ps1` from `raincheck/`). `npm test` is Vitest. Playwright needs the screen and the API already running.
