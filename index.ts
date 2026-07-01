import express, { Request, Response, NextFunction } from 'express';
import path from 'path';
import rateLimit from 'express-rate-limit';
import dotenv from 'dotenv';
import { cleanEnv, port, str } from 'envalid';

dotenv.config();

const env = cleanEnv(process.env, {
  PORT: port({ default: 8080 }),
  NODE_SECRET_KEY: str({ default: 'development-secret-key-replace-in-production' }),
});

const app = express();

// Trust reverse proxy for rate limiting to work correctly
app.set('trust proxy', 1);

const limiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 100, // Limit each IP to 100 requests per `window` (here, per 15 minutes)
  standardHeaders: true, // Return rate limit info in the `RateLimit-*` headers
  legacyHeaders: false, // Disable the `X-RateLimit-*` headers
});

// Apply the rate limiting middleware to all requests
app.use(limiter);

// ── Security Headers Middleware ────────────────────
app.use((req: Request, res: Response, next: NextFunction) => {
  res.setHeader(
    "Content-Security-Policy",
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: https: blob:; connect-src 'self' http://127.0.0.1:8000 http://localhost:5000 http://localhost:7545 ws://localhost:* wss://localhost:*; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none';"
  );
  res.setHeader(
    "Permissions-Policy",
    "camera=(self), microphone=(), geolocation=(), payment=(), usb=(), accelerometer=(), gyroscope=(), magnetometer=()"
  );
  res.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("X-Frame-Options", "DENY");
  next();
});

// ── Static File Serving ────────────────────────────
// Serve the built React application
app.use(express.static(path.join(__dirname, 'dist')));

// ── Routes ─────────────────────────────────────────

// Serve index.html for all other routes to support React Router SPA
app.get('*', (req: Request, res: Response) => {
  res.sendFile(path.join(__dirname, 'dist/index.html'));
});

// ── Start Server ───────────────────────────────────
const PORT = env.PORT;

app.listen(PORT, () => {
  console.log(`Server listening on http://localhost:${PORT}`);
});
