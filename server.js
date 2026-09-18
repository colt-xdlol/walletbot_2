import express from 'express';
import session from 'express-session';
import path from 'path';
import crypto from 'crypto';
import ejs from 'ejs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = 3000;

// Configuration
const TEST_MODE = (process.env.TEST_MODE || 'true').toLowerCase() !== 'false';
const BOT_TOKEN = process.env.BOT_TOKEN || '5001151811:AAFbZV5DKE4-8WiQXk3YEsmWQTq8CwGDoPk/test';
const ADMIN_TG_ID = parseInt(process.env.ADMIN_TG_ID || '5000479220', 10);

// In-Memory Data Store (mocking SQLite database)
let nextUserId = 3;
let nextTransId = 3;
let nextDepositRequestId = 1;

const users = [
  {
    id: 1,
    tg_id: 100000001,
    username: 'demo_user',
    first_name: 'Демо Пользователь',
    password_hash: null,
    wallet_address: 'W8X9K2M4P7Q1Z3Y',
    balance: 250.00,
    created_at: new Date().toISOString().replace('T', ' ').slice(0, 19),
    banned: 0
  },
  {
    id: 2,
    tg_id: ADMIN_TG_ID,
    username: 'amaral',
    first_name: 'Администратор',
    password_hash: null,
    wallet_address: 'W1A4B8C2D6E9F7G',
    balance: 5000.00,
    created_at: new Date().toISOString().replace('T', ' ').slice(0, 19),
    banned: 0
  }
];

const transactions = [
  {
    id: 1,
    user_id: 1,
    tg_id: 100000001,
    username: 'demo_user',
    transaction_type: 'deposit',
    amount: 250.00,
    description: 'Стартовое пополнение баланса',
    status: 'completed',
    created_at: new Date(Date.now() - 3600000).toISOString().replace('T', ' ').slice(0, 19)
  },
  {
    id: 2,
    user_id: 2,
    tg_id: ADMIN_TG_ID,
    username: 'amaral',
    transaction_type: 'deposit',
    amount: 5000.00,
    description: 'Пополнение баланса администратора',
    status: 'completed',
    created_at: new Date(Date.now() - 7200000).toISOString().replace('T', ' ').slice(0, 19)
  }
];

const settings = {
  min_deposit: 10.0,
  max_deposit: 100000.0,
  min_withdraw: 50.0,
  max_withdraw: 50000.0
};

const depositRequests = [];

function generateWalletAddress() {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  let addr = 'W';
  for (let i = 0; i < 15; i++) {
    addr += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return addr;
}

function addTransaction(userId, type, amount, description = '', status = 'completed') {
  const user = users.find(u => u.id === userId);
  const trans = {
    id: nextTransId++,
    user_id: userId,
    tg_id: user ? user.tg_id : null,
    username: user ? user.username : '',
    transaction_type: type,
    amount: parseFloat(amount),
    description: description || '',
    status: status,
    created_at: new Date().toISOString().replace('T', ' ').slice(0, 19)
  };
  transactions.unshift(trans);
  return trans;
}

// Telegram Web App Validation
function validateTelegramData(initData, botToken) {
  try {
    const params = new URLSearchParams(initData);
    const hash = params.get('hash');
    if (!hash) return null;

    const dataCheckArr = [];
    params.forEach((val, key) => {
      if (key !== 'hash') {
        dataCheckArr.push(`${key}=${val}`);
      }
    });
    dataCheckArr.sort();
    const dataCheckString = dataCheckArr.join('\n');

    const secretKey = crypto.createHmac('sha256', 'WebAppData').update(botToken).digest();
    const calculatedHash = crypto.createHmac('sha256', secretKey).update(dataCheckString).digest('hex');

    if (calculatedHash === hash) {
      const userStr = params.get('user');
      return userStr ? JSON.parse(userStr) : null;
    }
    return null;
  } catch (err) {
    console.error('Validation error:', err);
    return null;
  }
}

// Middleware
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use('/static', express.static(path.join(__dirname, 'static')));

app.use(session({
  secret: process.env.SESSION_SECRET || crypto.randomBytes(32).toString('hex'),
  resave: false,
  saveUninitialized: false,
  cookie: {
    maxAge: 7 * 24 * 60 * 60 * 1000,
    httpOnly: true,
    sameSite: 'lax'
  }
}));

// Setup EJS template engine for .html files
app.engine('html', ejs.renderFile);
app.set('view engine', 'html');
app.set('views', path.join(__dirname, 'templates'));

// Routes

app.get('/', (req, res) => {
  if (req.session.user_id) {
    return res.redirect('/home');
  }
  res.render('login');
});

app.get('/login', (req, res) => {
  if (req.session.user_id) {
    return res.redirect('/home');
  }
  res.render('login');
});

app.get('/logout', (req, res) => {
  req.session.destroy(() => {
    res.redirect('/login');
  });
});

app.post('/auth', (req, res) => {
  const data = req.body || {};
  const initData = data.initData || '';
  let tgId = data.tg_id ? parseInt(data.tg_id, 10) : null;
  let username = (data.username || '').toLowerCase().trim();
  let firstName = (data.first_name || '').trim() || 'Пользователь';
  const isAdminRequest = !!data.isAdmin;

  if (initData) {
    const verifiedUser = validateTelegramData(initData, BOT_TOKEN);
    if (verifiedUser) {
      tgId = verifiedUser.id || tgId;
      username = (verifiedUser.username || username || '').toLowerCase().trim();
      firstName = verifiedUser.first_name || firstName || 'Пользователь';
    }
  }

  // Test mode fallback when not running inside real Telegram WebApp
  if (!tgId && TEST_MODE) {
    if (isAdminRequest) {
      tgId = ADMIN_TG_ID;
      username = 'amaral';
      firstName = 'Администратор';
    } else {
      tgId = 100000001;
      username = username || 'demo_user';
      firstName = firstName || 'Демо Пользователь';
    }
  }

  if (!tgId) {
    return res.status(400).json({
      success: false,
      error: 'Не удалось получить данные пользователя (tg_id). Откройте через Telegram бота.'
    });
  }

  if (!username) {
    username = `user_${tgId % 100000}`;
  }

  // Find or create user
  let user = users.find(u => u.tg_id === tgId);

  if (!user) {
    const walletAddress = generateWalletAddress();
    user = {
      id: nextUserId++,
      tg_id: tgId,
      username: username,
      first_name: firstName,
      password_hash: null,
      wallet_address: walletAddress,
      balance: 100.00, // Initial balance for new users in demo
      created_at: new Date().toISOString().replace('T', ' ').slice(0, 19),
      banned: 0
    };
    users.push(user);
    addTransaction(user.id, 'deposit', 100.00, 'Приветственный бонус');
  } else {
    if (user.banned === 1) {
      return res.status(403).json({ success: false, error: 'Вы забанены' });
    }
    user.username = username;
    if (firstName) user.first_name = firstName;
  }

  // Set session
  req.session.user_id = user.id;
  req.session.tg_id = user.tg_id;
  req.session.username = user.username;
  req.session.first_name = user.first_name;
  req.session.balance = user.balance;
  if (user.tg_id === ADMIN_TG_ID || isAdminRequest) {
    req.session.admin = true;
  }

  return res.json({ success: true, redirect: '/home' });
});

app.get('/home', (req, res) => {
  const userId = req.session.user_id;
  if (!userId) {
    return res.redirect('/login');
  }

  const user = users.find(u => u.id === userId);
  if (!user) {
    req.session.destroy(() => res.redirect('/login'));
    return;
  }

  req.session.balance = user.balance;
  req.session.first_name = user.first_name;

  const userTransactions = transactions
    .filter(t => t.user_id === userId)
    .map(t => ({
      type: t.transaction_type,
      amount: t.amount,
      description: t.description || '',
      date: t.created_at
    }));

  res.render('home', {
    username: user.username,
    first_name: user.first_name || 'Пользователь',
    balance: user.balance,
    wallet_address: user.wallet_address,
    transactions: userTransactions,
    avatar_url: null
  });
});

app.post('/deposit', (req, res) => {
  const userId = req.session.user_id;
  if (!userId) {
    return res.status(401).json({ success: false, error: 'Unauthorized' });
  }

  const user = users.find(u => u.id === userId);
  if (!user) {
    return res.status(404).json({ success: false, error: 'Пользователь не найден' });
  }

  const amount = parseFloat(req.body.amount || 0);
  if (isNaN(amount) || amount <= 0) {
    return res.status(400).json({ success: false, error: 'Неверная сумма' });
  }

  if (amount < settings.min_deposit || amount > settings.max_deposit) {
    return res.status(400).json({
      success: false,
      error: `Сумма должна быть от ${settings.min_deposit.toFixed(2)} до ${settings.max_deposit.toFixed(2)} USDT`
    });
  }

  const reqId = nextDepositRequestId++;
  depositRequests.push({
    id: reqId,
    user_id: userId,
    amount: amount,
    status: 'pending',
    created_at: new Date().toISOString().replace('T', ' ').slice(0, 19)
  });

  // In test mode: also record transaction and credit so user sees immediate feedback
  if (TEST_MODE) {
    user.balance += amount;
    req.session.balance = user.balance;
    addTransaction(userId, 'deposit', amount, `Пополнение баланса на ${amount.toFixed(2)} USDT`);
    return res.json({
      success: true,
      message: `Заявка #${reqId} исполнена! На баланс зачислено ${amount.toFixed(2)} USDT.`
    });
  }

  return res.json({
    success: true,
    message: `Заявка #${reqId} создана! Отправьте ${amount.toFixed(2)} USDT на @amaral и ожидайте подтверждения.`
  });
});

app.post('/transfer', (req, res) => {
  const userId = req.session.user_id;
  if (!userId) {
    return res.status(401).json({ success: false, error: 'Unauthorized' });
  }

  const sender = users.find(u => u.id === userId);
  if (!sender) {
    return res.status(404).json({ success: false, error: 'Отправитель не найден' });
  }

  const recipientAddress = (req.body.recipient_address || '').trim();
  const amount = parseFloat(req.body.amount || 0);
  const description = (req.body.description || '').trim();

  if (!recipientAddress) {
    return res.status(400).json({ success: false, error: 'Введите адрес получателя' });
  }

  if (isNaN(amount) || amount <= 0) {
    return res.status(400).json({ success: false, error: 'Неверная сумма' });
  }

  if (sender.balance < amount) {
    return res.status(400).json({ success: false, error: 'Недостаточно средств' });
  }

  const recipient = users.find(u => u.wallet_address === recipientAddress);
  if (!recipient) {
    return res.status(404).json({ success: false, error: 'Адрес получателя не найден' });
  }

  if (recipient.id === sender.id) {
    return res.status(400).json({ success: false, error: 'Нельзя переводить самому себе' });
  }

  sender.balance -= amount;
  recipient.balance += amount;
  req.session.balance = sender.balance;

  const descSender = `Перевод пользователю @${recipient.username}: ${amount.toFixed(2)} USDT` + (description ? ` (${description})` : '');
  const descRecipient = `Перевод от @${sender.username}: ${amount.toFixed(2)} USDT` + (description ? ` (${description})` : '');

  addTransaction(sender.id, 'transfer_out', amount, descSender);
  addTransaction(recipient.id, 'transfer_in', amount, descRecipient);

  return res.json({
    success: true,
    new_balance: sender.balance,
    message: `✅ Успешно! Вы перевели ${amount.toFixed(2)} USDT на адрес ${recipientAddress}`,
    recipient_username: recipient.username
  });
});

app.get('/transactions', (req, res) => {
  const userId = req.session.user_id;
  if (!userId) {
    return res.redirect('/login');
  }

  const user = users.find(u => u.id === userId);
  if (!user) {
    req.session.destroy(() => res.redirect('/login'));
    return;
  }

  const userTransactions = transactions
    .filter(t => t.user_id === userId)
    .map(t => ({
      type: t.transaction_type,
      amount: t.amount,
      description: t.description || '',
      date: t.created_at
    }));

  res.render('transactions', {
    username: user.username,
    transactions: userTransactions
  });
});

// Admin endpoints
app.get('/admin', (req, res) => {
  // Support quick admin login if query code is provided e.g. ?code=ADMIN123
  if (req.query.code === 'ADMIN123') {
    const adminUser = users.find(u => u.tg_id === ADMIN_TG_ID);
    if (adminUser) {
      req.session.user_id = adminUser.id;
      req.session.username = adminUser.username;
      req.session.first_name = adminUser.first_name;
      req.session.balance = adminUser.balance;
    }
    req.session.admin = true;
  }

  if (!req.session.admin) {
    return res.redirect('/login');
  }
  res.render('admin');
});

app.get('/admin/get_data', (req, res) => {
  if (!req.session.admin) {
    return res.status(401).json({ success: false, error: 'Unauthorized' });
  }

  const adminUsersList = users.map(u => ({
    tg_id: u.tg_id,
    username: u.username || '',
    first_name: u.first_name || '',
    balance: u.balance,
    banned: u.banned,
    created_at: u.created_at
  }));

  const adminTransactionsList = transactions.slice(0, 100).map(t => ({
    tg_id: t.tg_id || 0,
    username: t.username || '',
    type: t.transaction_type,
    amount: t.amount,
    description: t.description || '',
    date: t.created_at
  }));

  return res.json({
    success: true,
    settings: settings,
    users: adminUsersList,
    transactions: adminTransactionsList
  });
});

app.post('/admin/give_balance', (req, res) => {
  if (!req.session.admin) {
    return res.status(401).json({ success: false, error: 'Unauthorized' });
  }

  const tgId = parseInt(req.body.tg_id, 10);
  const amount = parseFloat(req.body.amount || 0);

  if (isNaN(amount) || amount <= 0) {
    return res.status(400).json({ success: false, error: 'Неверная сумма' });
  }

  const user = users.find(u => u.tg_id === tgId);
  if (!user) {
    return res.status(404).json({ success: false, error: 'Пользователь не найден' });
  }

  user.balance += amount;
  addTransaction(user.id, 'admin_give', amount, `Выдача администратором: ${amount.toFixed(2)} USDT`);

  return res.json({ success: true });
});

app.post('/admin/ban_user', (req, res) => {
  if (!req.session.admin) {
    return res.status(401).json({ success: false, error: 'Unauthorized' });
  }

  const tgId = parseInt(req.body.tg_id, 10);
  const user = users.find(u => u.tg_id === tgId);
  if (user) {
    user.banned = 1;
  }
  return res.json({ success: true });
});

app.post('/admin/unban_user', (req, res) => {
  if (!req.session.admin) {
    return res.status(401).json({ success: false, error: 'Unauthorized' });
  }

  const tgId = parseInt(req.body.tg_id, 10);
  const user = users.find(u => u.tg_id === tgId);
  if (user) {
    user.banned = 0;
  }
  return res.json({ success: true });
});

app.post('/admin/update_settings', (req, res) => {
  if (!req.session.admin) {
    return res.status(401).json({ success: false, error: 'Unauthorized' });
  }

  const body = req.body || {};
  if (body.min_deposit !== undefined) settings.min_deposit = parseFloat(body.min_deposit);
  if (body.max_deposit !== undefined) settings.max_deposit = parseFloat(body.max_deposit);
  if (body.min_withdraw !== undefined) settings.min_withdraw = parseFloat(body.min_withdraw);
  if (body.max_withdraw !== undefined) settings.max_withdraw = parseFloat(body.max_withdraw);

  return res.json({ success: true });
});

// Health check
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', runtime: 'nodejs', framework: 'express' });
});

// Start server
app.listen(PORT, '0.0.0.0', () => {
  console.log(`Server running on port ${PORT}`);
});
