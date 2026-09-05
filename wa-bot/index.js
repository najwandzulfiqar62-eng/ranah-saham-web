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
// Ke mana pesan grup ditanyakan jawabannya. Bot ini SENGAJA tidak tahu apa-apa
// soal saham -- seluruh logikanya ada di app Python (POST /api/wa/command).
const APP_BASE_URL = (process.env.APP_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
// Volume di docker-compose di-mount ke /data supaya sesi login (multi-file
// auth state) bertahan lintas restart container -- tanpa ini admin harus
// scan QR ulang tiap kali container di-redeploy.
const AUTH_DIR = process.env.WA_AUTH_DIR || path.join(__dirname, "auth");

const logger = pino({ level: process.env.WA_LOG_LEVEL || "warn" });

let sock = null;
let isConnected = false;
let lastQrPng = null; // Buffer PNG QR terbaru, null kalau sudah login/belum ada

// Daftar lengkap (semua saham akumulasi berulang, semua filing hari itu) bisa
// melampaui batas satu pesan WhatsApp. Dipotong per BARIS, bukan per karakter,
// supaya tidak ada baris data yang terbelah di tengah -- lebih baik beberapa
// pesan berurutan daripada daftar yang diam-diam terpenggal.
const BATAS_PESAN = 3500;

function pecahPesan(teks, batas = BATAS_PESAN) {
  if (teks.length <= batas) return [teks];
  const bagian = [];
  let buffer = "";
  for (const baris of teks.split("\n")) {
    // Satu baris tunggal yang lebih panjang dari batas: kirim apa adanya,
    // biar WhatsApp yang mengurus daripada memotongnya sembarangan.
    if (baris.length >= batas) {
      if (buffer) { bagian.push(buffer); buffer = ""; }
      bagian.push(baris);
      continue;
    }
    if ((buffer + "\n" + baris).length > batas) {
      bagian.push(buffer);
      buffer = baris;
    } else {
      buffer = buffer ? buffer + "\n" + baris : baris;
    }
  }
  if (buffer) bagian.push(buffer);
  return bagian;
}

async function kirimTeks(jid, teks, quoted) {
  const bagian = pecahPesan(teks);
  for (let i = 0; i < bagian.length; i++) {
    const isi = bagian.length > 1 ? `${bagian[i]}\n\n_(${i + 1}/${bagian.length})_` : bagian[i];
    // Hanya pesan pertama yang mengutip, sisanya lanjutan.
    await sock.sendMessage(jid, { text: isi }, i === 0 && quoted ? { quoted } : undefined);
    if (i < bagian.length - 1) await new Promise((r) => setTimeout(r, 900));
  }
}

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

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify" || !GROUP_JID) return;
    for (const msg of messages || []) {
      try {
        // Hanya grup yang dikonfigurasi, dan JANGAN pernah menanggapi pesan
        // bot sendiri (kalau tidak, satu balasan bisa memicu balasan lagi).
        if (msg.key?.remoteJid !== GROUP_JID || msg.key?.fromMe) continue;
        const isi = msg.message?.conversation
          || msg.message?.extendedTextMessage?.text
          || "";
        if (!isi.trim()) continue;

        // WhatsApp modern sering mengidentifikasi peserta grup dengan LID
        // acak ("12345@lid"), BUKAN nomor teleponnya -- kalau cuma
        // `participant` yang dikirim, penanya tidak akan pernah cocok dengan
        // akun mana pun. Baileys menaruh nomor aslinya di field yang
        // berbeda-beda antar versi, jadi semua kandidat dikirim dan Python
        // yang memutuskan mana yang cocok.
        const kandidat = [
          msg.key.participantPn, msg.key.senderPn, msg.participantPn,
          msg.key.participantAlt, msg.key.participant, msg.participant,
        ].filter((v) => typeof v === "string" && v);
        const pengirim = kandidat[0] || msg.key.remoteJid;
        console.log(`[wa-bot] pesan grup dari ${kandidat.join(" | ") || "?"}: ${JSON.stringify(isi.slice(0, 60))}`);

        const res = await fetch(`${APP_BASE_URL}/api/wa/command`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${SECRET}` },
          body: JSON.stringify({ from: pengirim, candidates: kandidat, text: isi }),
        });
        if (!res.ok) {
          console.warn(`[wa-bot] /api/wa/command menjawab ${res.status}`);
          continue;
        }
        const { reply } = await res.json();
        // reply null = memang bukan perintah; obrolan biasa tidak disahut.
        if (reply) await kirimTeks(GROUP_JID, reply, msg);
      } catch (e) {
        console.error("[wa-bot] Gagal memproses pesan:", e);
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
    // Lewat kirimTeks juga: digest harian ikut memuat daftar lengkap, jadi
    // ia bisa melampaui batas satu pesan persis seperti balasan perintah.
    await kirimTeks(GROUP_JID, text);
    res.json({ ok: true });
  } catch (e) {
    res.status(502).json({ error: `gagal mengirim pesan: ${e.message}` });
  }
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`[wa-bot] HTTP listening on :${PORT}`);
});
