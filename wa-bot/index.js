const path = require("path");
const express = require("express");
const QRCode = require("qrcode");
const pino = require("pino");
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} = require("@whiskeysockets/baileys");

const PORT = parseInt(process.env.WA_BOT_PORT || "3901", 10);
const SECRET = process.env.WA_BOT_SECRET || "";
const GROUP_JID = (process.env.WA_GROUP_JID || "").trim();
// Volume di docker-compose di-mount ke /data supaya sesi login (multi-file
// auth state) bertahan lintas restart container -- tanpa ini admin harus
// scan QR ulang tiap kali container di-redeploy.
const AUTH_DIR = process.env.WA_AUTH_DIR || path.join(__dirname, "auth");

const logger = pino({ level: process.env.WA_LOG_LEVEL || "warn" });

let sock = null;
let isConnected = false;
let lastQrPng = null; // Buffer PNG QR terbaru, null kalau sudah login/belum ada

if (!SECRET) {
  console.warn(
    "[wa-bot] PERINGATAN: WA_BOT_SECRET kosong -- endpoint HTTP TIDAK terproteksi. " +
    "Aman selama service ini hanya reachable dari jaringan internal docker-compose."
  );
}

async function startSock() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    auth: state,
    logger,
    printQRInTerminal: false,
    browser: ["Ranah Saham Bot", "Chrome", "1.0"],
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      lastQrPng = await QRCode.toBuffer(qr, { width: 300 });
      const ascii = await QRCode.toString(qr, { type: "terminal", small: true });
      console.log("[wa-bot] Scan QR ini dengan WhatsApp (Perangkat Tertaut):\n" + ascii);
    }

    if (connection === "open") {
      isConnected = true;
      lastQrPng = null;
      console.log("[wa-bot] Terhubung ke WhatsApp.");
    }

    if (connection === "close") {
      isConnected = false;
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      const loggedOut = statusCode === DisconnectReason.loggedOut;
      console.warn(`[wa-bot] Koneksi terputus (status ${statusCode}). ${loggedOut ? "Logged out -- perlu scan QR ulang." : "Mencoba menyambung ulang..."}`);
      if (!loggedOut) {
        startSock().catch((e) => console.error("[wa-bot] Gagal menyambung ulang:", e));
      }
    }
  });
}

startSock().catch((e) => {
  console.error("[wa-bot] Gagal memulai koneksi WhatsApp:", e);
});

const app = express();
app.use(express.json());

app.get("/healthz", (_req, res) => res.json({ ok: true }));

app.use((req, res, next) => {
  if (req.path === "/healthz") return next();
  if (!SECRET) return next();
  const auth = req.get("authorization") || "";
  if (auth === `Bearer ${SECRET}`) return next();
  return res.status(401).json({ error: "unauthorized" });
});

app.get("/status", (_req, res) => {
  res.json({
    connected: isConnected,
    groupConfigured: Boolean(GROUP_JID),
    groupJid: GROUP_JID || null,
  });
});

app.get("/qr", (_req, res) => {
  if (isConnected) return res.status(404).json({ error: "sudah terhubung, tidak ada QR aktif" });
  if (!lastQrPng) return res.status(404).json({ error: "QR belum tersedia, coba lagi sebentar" });
  res.set("Content-Type", "image/png");
  res.send(lastQrPng);
});

app.get("/groups", async (_req, res) => {
  if (!isConnected || !sock) return res.status(503).json({ error: "belum terhubung ke WhatsApp" });
  try {
    const groups = await sock.groupFetchAllParticipating();
    const list = Object.values(groups).map((g) => ({ id: g.id, subject: g.subject }));
    res.json({ groups: list });
  } catch (e) {
    res.status(502).json({ error: `gagal mengambil daftar grup: ${e.message}` });
  }
});

app.post("/send", async (req, res) => {
  const text = req.body?.text;
  if (!text || typeof text !== "string") {
    return res.status(400).json({ error: "field 'text' (string) wajib diisi" });
  }
  if (!GROUP_JID) {
    return res.status(500).json({ error: "WA_GROUP_JID belum diset -- lihat /groups untuk menemukan JID grup" });
  }
  if (!isConnected || !sock) {
    return res.status(503).json({ error: "belum terhubung ke WhatsApp" });
  }
  try {
    await sock.sendMessage(GROUP_JID, { text });
    res.json({ ok: true });
  } catch (e) {
    res.status(502).json({ error: `gagal mengirim pesan: ${e.message}` });
  }
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`[wa-bot] HTTP listening on :${PORT}`);
});
