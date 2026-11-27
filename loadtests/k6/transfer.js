// k6 load test: login, create transfers (unique Idempotency-Key each), read balance.
//
//   make loadtest-up && make create-admin EMAIL=admin@example.com
//   ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=... make loadtest
//   make verify && make loadtest-report
//
// Open model (constant-arrival-rate): k6 starts iterations at a FIXED rate no matter how slow the
// system answers, so latency growth shows up as latency, not as hidden throughput loss. If the
// system cannot keep up, k6 reports `dropped_iterations` instead of silently slowing down.
import http from 'k6/http';
import exec from 'k6/execution';
import { check, fail } from 'k6';
import { Counter, Rate } from 'k6/metrics';

const AUTH_URL = __ENV.AUTH_URL || 'http://localhost:8001';
const WALLET_URL = __ENV.WALLET_URL || 'http://localhost:8002';
const ADMIN_EMAIL = __ENV.ADMIN_EMAIL || '';
const ADMIN_PASSWORD = __ENV.ADMIN_PASSWORD || '';
const USERS = Number(__ENV.USERS || 50);
const DURATION_SECONDS = Number(__ENV.DURATION_SECONDS || 60);
const TRANSFER_RATE = Number(__ENV.TRANSFER_RATE || 50); // new transfers per second
const READ_RATE = Number(__ENV.READ_RATE || 100); // balance reads per second
const LOGIN_RATE = Number(__ENV.LOGIN_RATE || 2); // logins per second (bcrypt makes each one expensive)
const REPLAY_RATIO = Number(__ENV.REPLAY_RATIO || 0.05); // share of transfers re-sent with the same key
const FUNDING_PAISE = Number(__ENV.FUNDING_PAISE || 100000000); // INR 1,000,000 per user
const RUN_ID = __ENV.RUN_ID || String(Date.now());
const SUMMARY_PATH = __ENV.SUMMARY_PATH || 'loadtests/results/summary.json';
const PASSWORD = 'load-test-password-1';

const transfersCreated = new Counter('transfers_created'); // committed transfers, replays excluded
const balanceReads = new Counter('balance_reads_ok');
const loginsOk = new Counter('logins_ok');
const replayOk = new Rate('idempotency_replay_ok'); // replay answered from the stored response?

function arrival(execName, rate, flow, preAllocatedVUs, maxVUs) {
  return {
    executor: 'constant-arrival-rate',
    exec: execName,
    rate: rate,
    timeUnit: '1s',
    duration: DURATION_SECONDS + 's',
    preAllocatedVUs: preAllocatedVUs,
    maxVUs: maxVUs,
    tags: { flow: flow },
  };
}

const scenarios = {};
if (TRANSFER_RATE > 0) scenarios.transfers = arrival('transferFlow', TRANSFER_RATE, 'transfer', 50, 500);
if (READ_RATE > 0) scenarios.balance_reads = arrival('readBalance', READ_RATE, 'read', 20, 300);
if (LOGIN_RATE > 0) scenarios.logins = arrival('loginFlow', LOGIN_RATE, 'login', 10, 100);

export const options = {
  setupTimeout: '900s', // registering + logging in N users costs N bcrypt hashes
  scenarios: scenarios,
  thresholds: {
    http_req_failed: ['rate<0.01'],
    checks: ['rate>0.99'],
    'http_req_duration{flow:transfer}': ['p(95)<500'],
    'http_req_duration{flow:read}': ['p(95)<200'],
    'http_req_duration{flow:login}': ['p(95)<1500'],
    idempotency_replay_ok: ['rate==1'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
};

const JSON_HEADERS = { 'Content-Type': 'application/json' };

function authHeaders(token, extra) {
  return Object.assign({ Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }, extra || {});
}

function login(email, password) {
  const res = http.post(
    AUTH_URL + '/auth/login',
    JSON.stringify({ email: email, password: password }),
    { headers: JSON_HEADERS, tags: { name: 'POST /auth/login' } }
  );
  if (res.status !== 200) fail('login failed for ' + email + ': ' + res.status + ' ' + res.body);
  return res.json('access_token');
}

// Runs once before the load: creates USERS funded accounts. Tokens expire after JWT_EXPIRE_MINUTES
// (30 by default), so keep a run shorter than that.
export function setup() {
  if (!ADMIN_EMAIL || !ADMIN_PASSWORD) {
    fail('ADMIN_EMAIL and ADMIN_PASSWORD are required (create the admin with: make create-admin EMAIL=...)');
  }
  if (USERS < 2) fail('USERS must be at least 2');

  const adminToken = login(ADMIN_EMAIL, ADMIN_PASSWORD);
  const users = [];
  for (let i = 0; i < USERS; i++) {
    const email = 'load-' + RUN_ID + '-' + i + '@example.com';
    const registered = http.post(
      AUTH_URL + '/auth/register',
      JSON.stringify({ email: email, password: PASSWORD }),
      { headers: JSON_HEADERS, tags: { name: 'POST /auth/register' } }
    );
    if (registered.status !== 201) fail('register failed: ' + registered.status + ' ' + registered.body);

    const token = login(email, PASSWORD);
    const wallet = http.post(WALLET_URL + '/wallets', null, {
      headers: authHeaders(token),
      tags: { name: 'POST /wallets' },
    });
    if (wallet.status !== 201) fail('create wallet failed: ' + wallet.status + ' ' + wallet.body);
    const walletId = wallet.json('id');

    const funded = http.post(
      WALLET_URL + '/wallets/' + walletId + '/deposit',
      JSON.stringify({ amount: FUNDING_PAISE }),
      { headers: authHeaders(adminToken), tags: { name: 'POST /wallets/{id}/deposit' } }
    );
    if (funded.status !== 201) fail('deposit failed: ' + funded.status + ' ' + funded.body);

    users.push({ email: email, token: token, walletId: walletId });
  }
  return { users: users };
}

export function transferFlow(data) {
  const users = data.users;
  const index = exec.scenario.iterationInTest; // unique across all VUs of this scenario
  const sender = users[index % users.length];
  const offset = 1 + Math.floor(Math.random() * (users.length - 1)); // never the sender itself
  const receiver = users[(index + offset) % users.length];

  const key = 'k6-' + RUN_ID + '-' + index; // unique idempotency key for every transfer
  const payload = JSON.stringify({
    to_wallet_id: receiver.walletId,
    amount: 1 + Math.floor(Math.random() * 100), // 1..100 paise: far below what every user holds
  });
  const params = {
    headers: authHeaders(sender.token, { 'Idempotency-Key': key, 'X-Request-ID': key }),
    tags: { name: 'POST /transfers' },
  };

  const res = http.post(WALLET_URL + '/transfers', payload, params);
  const created = check(res, {
    'transfer created (201)': (r) => r.status === 201,
    'transfer has an id': (r) => r.status === 201 && !!r.json('transfer_id'),
  });
  if (!created) return;
  transfersCreated.add(1);

  // Idempotency under load: re-send a few requests with the SAME key. The answer must be the stored
  // response (replay header, same transfer id), and the money must not move twice (verified by SQL).
  if (Math.random() < REPLAY_RATIO) {
    const replay = http.post(
      WALLET_URL + '/transfers',
      payload,
      Object.assign({}, params, { tags: { name: 'POST /transfers (replay)', flow: 'replay' } })
    );
    replayOk.add(
      replay.status === 201 &&
        replay.headers['Idempotent-Replay'] === 'true' &&
        replay.json('transfer_id') === res.json('transfer_id')
    );
  }
}

export function readBalance(data) {
  const user = data.users[Math.floor(Math.random() * data.users.length)];
  const res = http.get(WALLET_URL + '/wallets/me/balance', {
    headers: authHeaders(user.token),
    tags: { name: 'GET /wallets/me/balance' },
  });
  const ok = check(res, {
    'balance 200': (r) => r.status === 200,
    'balance is an integer': (r) => r.status === 200 && Number.isInteger(r.json('balance')),
  });
  if (ok) balanceReads.add(1);
}

export function loginFlow(data) {
  const user = data.users[Math.floor(Math.random() * data.users.length)];
  const res = http.post(
    AUTH_URL + '/auth/login',
    JSON.stringify({ email: user.email, password: PASSWORD }),
    { headers: JSON_HEADERS, tags: { name: 'POST /auth/login' } }
  );
  const ok = check(res, {
    'login 200': (r) => r.status === 200,
    'login returns a token': (r) => r.status === 200 && !!r.json('access_token'),
  });
  if (ok) loginsOk.add(1);
}

function line(label, value) {
  return '  ' + (label + '                              ').slice(0, 34) + value + '\n';
}

function latency(data, flow) {
  const metric = data.metrics['http_req_duration{flow:' + flow + '}'];
  if (!metric || !metric.values) return null;
  const v = metric.values;
  return 'p50 ' + v.med.toFixed(1) + ' ms   p95 ' + v['p(95)'].toFixed(1) + ' ms   p99 ' + v['p(99)'].toFixed(1) + ' ms';
}

function count(data, name) {
  const metric = data.metrics[name];
  return metric && metric.values ? metric.values.count || 0 : 0;
}

export function handleSummary(data) {
  const meta = {
    run_id: RUN_ID,
    users: USERS,
    duration_seconds: DURATION_SECONDS,
    transfer_rate: TRANSFER_RATE,
    read_rate: READ_RATE,
    login_rate: LOGIN_RATE,
    replay_ratio: REPLAY_RATIO,
    auth_url: AUTH_URL,
    wallet_url: WALLET_URL,
  };
  let text = '\nLoad test finished (' + DURATION_SECONDS + ' s, ' + USERS + ' users)\n';
  text += line('transfers committed', count(data, 'transfers_created') + '  (' + (count(data, 'transfers_created') / DURATION_SECONDS).toFixed(1) + ' per second)');
  text += line('balance reads', count(data, 'balance_reads_ok') + '  (' + (count(data, 'balance_reads_ok') / DURATION_SECONDS).toFixed(1) + ' per second)');
  text += line('logins', count(data, 'logins_ok') + '  (' + (count(data, 'logins_ok') / DURATION_SECONDS).toFixed(1) + ' per second)');
  ['transfer', 'read', 'login', 'replay'].forEach(function (flow) {
    const l = latency(data, flow);
    if (l) text += line('latency ' + flow, l);
  });
  text += line('dropped iterations', count(data, 'dropped_iterations') + '  (non-zero = the system could not keep up)');
  text += '\nFull data: ' + SUMMARY_PATH + '   |   next: make verify && make loadtest-report\n';

  const result = { stdout: text };
  result[SUMMARY_PATH] = JSON.stringify({ meta: meta, metrics: data.metrics, state: data.state }, null, 2);
  return result;
}
