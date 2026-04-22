'use strict';

const crypto = require('crypto');
const https = require('https');
const { Resend } = require('resend');

// In-memory sessions keyed by LINE userId.
// Note: stateless across Vercel cold-starts — acceptable for a small clinic.
// For higher durability, replace with Vercel KV (ioredis).
const sessions = new Map();
const SESSION_TTL_MS = 30 * 60 * 1000; // 30 min

// Periodic cleanup (runs within warm instances)
setInterval(() => {
  const cutoff = Date.now() - SESSION_TTL_MS;
  for (const [k, v] of sessions) {
    if (v.updatedAt < cutoff) sessions.delete(k);
  }
}, 5 * 60 * 1000);

// ── Clinic schedule ──────────────────────────────────────────────────────────
const MORNING_SLOTS = ['9:00', '9:30', '10:00', '10:30', '11:00', '11:30'];
const AFTERNOON_SLOTS = ['14:00', '14:30', '15:00', '15:30', '16:00', '16:30', '17:00'];
const ALL_SLOTS = [...MORNING_SLOTS, ...AFTERNOON_SLOTS]; // 13 items — LINE quick reply max
const DAYS_JA = ['日', '月', '火', '水', '木', '金', '土'];

function getAvailableDates(count = 7) {
  const dates = [];
  const d = new Date();
  d.setDate(d.getDate() + 1); // start from tomorrow
  while (dates.length < count) {
    const day = d.getDay();
    if (day !== 0) { // skip Sunday (定休日)
      const label = `${d.getMonth() + 1}/${d.getDate()}(${DAYS_JA[day]})`;
      const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      dates.push({ label, value });
    }
    d.setDate(d.getDate() + 1);
  }
  return dates;
}

// ── LINE API helpers ─────────────────────────────────────────────────────────
function linePost(path, body) {
  const data = JSON.stringify(body);
  return new Promise((resolve, reject) => {
    const req = https.request({
      hostname: 'api.line.me',
      path: `/v2/bot${path}`,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${process.env.LINE_CHANNEL_ACCESS_TOKEN}`,
        'Content-Length': Buffer.byteLength(data),
      },
    }, (res) => {
      let buf = '';
      res.on('data', c => { buf += c; });
      res.on('end', () => resolve({ status: res.statusCode, body: buf }));
    });
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

const replyMsg = (replyToken, messages) =>
  linePost('/message/reply', { replyToken, messages: [].concat(messages) });

const pushMsg = (to, messages) =>
  linePost('/message/push', { to, messages: [].concat(messages) });

function verifySignature(rawBody, signature, secret) {
  const hash = crypto.createHmac('sha256', secret).update(rawBody).digest('base64');
  return hash === signature;
}

// ── Session helpers ──────────────────────────────────────────────────────────
function getSession(userId) {
  return sessions.get(userId) || { step: 'idle', updatedAt: 0 };
}

function setSession(userId, patch) {
  const prev = sessions.get(userId) || {};
  const next = { ...prev, ...patch, updatedAt: Date.now() };
  sessions.set(userId, next);
  return next;
}

// ── Reusable messages ────────────────────────────────────────────────────────
function menuMessage() {
  return {
    type: 'text',
    text: 'ひかり鍼灸整骨院の公式LINEです。\nご予約・お問い合わせをどうぞ。',
    quickReply: {
      items: [
        { type: 'action', action: { type: 'message', label: '📅 予約する',   text: '予約' } },
        { type: 'action', action: { type: 'message', label: '📋 予約確認',   text: '予約確認' } },
        { type: 'action', action: { type: 'message', label: '📞 電話番号',   text: '電話番号' } },
      ],
    },
  };
}

function dateSelectMessage() {
  const dates = getAvailableDates(7);
  return {
    type: 'text',
    text: 'ご希望の予約日をお選びください。',
    quickReply: {
      items: dates.map(d => ({
        type: 'action',
        action: {
          type: 'postback',
          label: d.label,
          data: `action=date&value=${d.value}&label=${encodeURIComponent(d.label)}`,
          displayText: d.label,
        },
      })),
    },
  };
}

function timeSelectMessage(dateLabel) {
  return {
    type: 'text',
    text: `${dateLabel} のご希望時間をお選びください。`,
    quickReply: {
      items: ALL_SLOTS.map(t => ({
        type: 'action',
        action: {
          type: 'postback',
          label: t,
          data: `action=time&value=${encodeURIComponent(t)}`,
          displayText: t,
        },
      })),
    },
  };
}

function confirmMessage(s) {
  return {
    type: 'text',
    text: `【予約内容の確認】\n\n日時: ${s.dateLabel} ${s.time}\nお名前: ${s.name} 様\n電話番号: ${s.phone}\n\nこの内容でよろしいですか？`,
    quickReply: {
      items: [
        { type: 'action', action: { type: 'postback', label: '✅ 確定する', data: 'action=confirm', displayText: '確定する' } },
        { type: 'action', action: { type: 'postback', label: '✏️ やり直す', data: 'action=restart', displayText: 'やり直す' } },
      ],
    },
  };
}

// ── Email notification ───────────────────────────────────────────────────────
async function notifyByEmail(s) {
  if (!process.env.RESEND_API_KEY || !process.env.CLINIC_EMAIL) return;
  const resend = new Resend(process.env.RESEND_API_KEY);
  await resend.emails.send({
    from: 'onboarding@resend.dev',
    to: process.env.CLINIC_EMAIL,
    subject: `【新規LINE予約】${s.name} 様 ${s.dateLabel} ${s.time}`,
    html: `
      <h2 style="color:#1D9E75">新規LINE予約</h2>
      <table border="1" cellpadding="8" cellspacing="0"
             style="border-collapse:collapse;font-size:14px;border-color:#ddd">
        <tr><td style="background:#f5f5f5;width:100px">日時</td><td>${s.dateLabel} ${s.time}</td></tr>
        <tr><td style="background:#f5f5f5">お名前</td><td>${s.name} 様</td></tr>
        <tr><td style="background:#f5f5f5">電話番号</td><td>${s.phone}</td></tr>
      </table>
    `,
  });
}

// ── Event handler ────────────────────────────────────────────────────────────
async function handleEvent(event) {
  const userId = event.source.userId;

  // ── Follow / Unfollow ──
  if (event.type === 'follow') {
    await replyMsg(event.replyToken, [
      { type: 'text', text: 'ひかり鍼灸整骨院へようこそ！\nLINEから簡単にご予約いただけます。' },
      menuMessage(),
    ]);
    return;
  }
  if (event.type === 'unfollow') {
    sessions.delete(userId);
    return;
  }

  // ── Text message ──
  if (event.type === 'message' && event.message.type === 'text') {
    const text = event.message.text.trim();
    const session = getSession(userId);

    // キャンセルワードはどのステップでも受け付ける
    if (text === 'キャンセル' || text === 'やめる' || text === '戻る') {
      sessions.delete(userId);
      await replyMsg(event.replyToken, {
        type: 'text',
        text: '操作をキャンセルしました。',
        quickReply: { items: [{ type: 'action', action: { type: 'message', label: '📅 予約する', text: '予約' } }] },
      });
      return;
    }

    if (text === '予約' || text === '予約する') {
      setSession(userId, { step: 'select_date' });
      await replyMsg(event.replyToken, dateSelectMessage());
      return;
    }

    if (text === '予約確認') {
      if (session.confirmed) {
        await replyMsg(event.replyToken, {
          type: 'text',
          text: `【ご予約内容】\n\n日時: ${session.dateLabel} ${session.time}\nお名前: ${session.name} 様\n電話番号: ${session.phone}\n\nご来院をお待ちしております！`,
        });
      } else {
        await replyMsg(event.replyToken, {
          type: 'text',
          text: '現在、予約はございません。',
          quickReply: { items: [{ type: 'action', action: { type: 'message', label: '📅 予約する', text: '予約' } }] },
        });
      }
      return;
    }

    if (text === '電話番号') {
      await replyMsg(event.replyToken, {
        type: 'text',
        text: 'ひかり鍼灸整骨院\n📞 079-228-9687\n\n受付時間: 9:00〜12:00 / 14:00〜19:00\n定休日: 日曜・祝日',
      });
      return;
    }

    // フリーテキスト入力ステップ
    if (session.step === 'enter_name') {
      const s = setSession(userId, { step: 'enter_phone', name: text });
      await replyMsg(event.replyToken, {
        type: 'text',
        text: `${text} 様、ありがとうございます。\n電話番号を入力してください。\n例: 080-1234-5678`,
      });
      return;
    }

    if (session.step === 'enter_phone') {
      const s = setSession(userId, { step: 'confirm', phone: text });
      await replyMsg(event.replyToken, confirmMessage(s));
      return;
    }

    // その他 → メニューを表示
    await replyMsg(event.replyToken, menuMessage());
    return;
  }

  // ── Postback ──
  if (event.type === 'postback') {
    const params = new URLSearchParams(event.postback.data);
    const action = params.get('action');

    if (action === 'date') {
      const value = params.get('value');
      const label = decodeURIComponent(params.get('label'));
      setSession(userId, { step: 'select_time', date: value, dateLabel: label });
      await replyMsg(event.replyToken, timeSelectMessage(label));
      return;
    }

    if (action === 'time') {
      const time = decodeURIComponent(params.get('value'));
      const s = setSession(userId, { step: 'enter_name', time });
      await replyMsg(event.replyToken, {
        type: 'text',
        text: `${s.dateLabel} ${time} ですね。\nご予約者のお名前を入力してください。\n例: 山田 太郎`,
      });
      return;
    }

    if (action === 'restart') {
      setSession(userId, { step: 'select_date' });
      await replyMsg(event.replyToken, dateSelectMessage());
      return;
    }

    if (action === 'confirm') {
      const s = getSession(userId);
      if (s.step !== 'confirm') {
        await replyMsg(event.replyToken, menuMessage());
        return;
      }

      setSession(userId, { step: 'complete', confirmed: true });

      // 院長へLINE通知
      if (process.env.LINE_ADMIN_USER_ID) {
        await pushMsg(process.env.LINE_ADMIN_USER_ID, {
          type: 'text',
          text: `📅 新規LINE予約\n\n日時: ${s.dateLabel} ${s.time}\nお名前: ${s.name} 様\n電話番号: ${s.phone}`,
        }).catch(console.error);
      }

      // メール通知
      await notifyByEmail(s).catch(console.error);

      await replyMsg(event.replyToken, {
        type: 'text',
        text: `✅ ご予約が完了しました！\n\n日時: ${s.dateLabel} ${s.time}\nお名前: ${s.name} 様\n\nご来院をお待ちしております。\n\n変更・キャンセルはこちらのLINEまたは\n☎ 079-228-9687 にてご連絡ください。`,
      });
      return;
    }
  }
}

// ── Vercel handler ───────────────────────────────────────────────────────────
module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).end();
  }

  // Read raw body (body parsing is disabled via config below)
  const rawBody = await new Promise((resolve, reject) => {
    let buf = '';
    req.on('data', c => { buf += c; });
    req.on('end', () => resolve(buf));
    req.on('error', reject);
  });

  const signature = req.headers['x-line-signature'];
  if (!signature || !verifySignature(rawBody, signature, process.env.LINE_CHANNEL_SECRET || '')) {
    return res.status(401).json({ error: 'Unauthorized' });
  }

  const body = JSON.parse(rawBody);
  await Promise.all((body.events || []).map(e => handleEvent(e).catch(console.error)));

  return res.status(200).end();
};

// Disable Vercel's automatic body parsing so we can read the raw body for HMAC verification
module.exports.config = { api: { bodyParser: false } };
