/**
 * setup_line_richmenu.js
 *
 * One-time script to create a LINE Rich Menu for the booking system.
 * Run once with your Channel Access Token set as an environment variable:
 *
 *   LINE_CHANNEL_ACCESS_TOKEN=xxxx node scripts/setup_line_richmenu.js
 *
 * The rich menu adds three tap areas at the bottom of the chat:
 *   [ 📅 予約する ] [ 📋 予約確認 ] [ 📞 電話する ]
 */

'use strict';

const https = require('https');

const TOKEN = process.env.LINE_CHANNEL_ACCESS_TOKEN;
if (!TOKEN) {
  console.error('Error: LINE_CHANNEL_ACCESS_TOKEN is not set.');
  process.exit(1);
}

function lineApi(method, path, body) {
  const data = body ? JSON.stringify(body) : null;
  return new Promise((resolve, reject) => {
    const req = https.request({
      hostname: 'api.line.me',
      path: `/v2/bot${path}`,
      method,
      headers: {
        'Authorization': `Bearer ${TOKEN}`,
        ...(data ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } : {}),
      },
    }, (res) => {
      let buf = '';
      res.on('data', c => { buf += c; });
      res.on('end', () => {
        try { resolve({ status: res.statusCode, body: JSON.parse(buf) }); }
        catch { resolve({ status: res.statusCode, body: buf }); }
      });
    });
    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

// Rich menu definition — 3 equal-width columns, height 250px
const richMenu = {
  size: { width: 2500, height: 843 },
  selected: true,
  name: 'ひかり鍼灸整骨院 予約メニュー',
  chatBarText: 'メニュー',
  areas: [
    {
      bounds: { x: 0, y: 0, width: 833, height: 843 },
      action: { type: 'message', text: '予約' },
    },
    {
      bounds: { x: 833, y: 0, width: 834, height: 843 },
      action: { type: 'message', text: '予約確認' },
    },
    {
      bounds: { x: 1667, y: 0, width: 833, height: 843 },
      action: { type: 'uri', uri: 'tel:0792289687' },
    },
  ],
};

async function main() {
  console.log('Creating rich menu...');
  const create = await lineApi('POST', '/richmenu', richMenu);
  if (create.status !== 200) {
    console.error('Failed to create rich menu:', create.body);
    process.exit(1);
  }
  const richMenuId = create.body.richMenuId;
  console.log(`Rich menu created: ${richMenuId}`);

  // Set as default rich menu for all users
  const setDefault = await lineApi('POST', `/user/all/richmenu/${richMenuId}`, null);
  if (setDefault.status !== 200 && setDefault.status !== 202) {
    console.error('Failed to set default rich menu:', setDefault.body);
    process.exit(1);
  }
  console.log('Default rich menu set successfully.');

  console.log(`
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 次のステップ: リッチメニュー画像のアップロード
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Rich menu ID: ${richMenuId}

LINE Official Account Manager でリッチメニューの画像（2500×843px）を
アップロードしてください。あるいは curl で直接アップロードできます:

  curl -X POST https://api-data.line.me/v2/bot/richmenu/${richMenuId}/content \\
    -H "Authorization: Bearer $LINE_CHANNEL_ACCESS_TOKEN" \\
    -H "Content-Type: image/jpeg" \\
    --data-binary @richmenu.jpg

推奨デザイン（横3分割, 2500×843px）:
  左: 📅 予約する (action: message → "予約")
  中: 📋 予約確認 (action: message → "予約確認")
  右: 📞 電話する (action: tel:0792289687)
`);
}

main().catch(err => { console.error(err); process.exit(1); });
