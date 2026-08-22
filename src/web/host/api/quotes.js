const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const { authorized } = require("./auth");

const TOKEN_URL = "https://api.groww.in/v1/token/api/access";
const HOLDINGS_URL = "https://api.groww.in/v1/holdings/user";
const LTP_URL = "https://api.groww.in/v1/live-data/ltp";

function checksum(secret, ts) {
  return crypto.createHash("sha256").update(String(secret) + String(ts)).digest("hex");
}

function loadSymbols() {
  const file = path.join(__dirname, "symbols.json");
  if (!fs.existsSync(file)) return [];
  try {
    const rows = JSON.parse(fs.readFileSync(file, "utf8"));
    return Array.isArray(rows) ? rows : [];
  } catch {
    return [];
  }
}

function fmtQty(value) {
  if (value == null) return "—";
  if (value === Math.trunc(value)) return String(Math.trunc(value));
  return Number(value).toFixed(2);
}

function fmtPrice(value) {
  if (value == null || value === "") return "—";
  const n = Number(String(value).replace(/,/g, ""));
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(2);
}

function fmtRet(last, cost) {
  if (last == null || !(cost > 0)) return { ret: "—", up: false, down: false };
  const pct = ((last - cost) / cost) * 100;
  const sign = pct >= 0 ? "+" : "";
  return {
    ret: `${sign}${pct.toFixed(1)}%`,
    up: pct > 0,
    down: pct < 0,
  };
}

async function accessToken() {
  const key = process.env.GROWW_API_KEY || "";
  const secret = process.env.GROWW_API_SECRET || "";
  if (!key || !secret) throw new Error("missing");
  const ts = String(Math.floor(Date.now() / 1000));
  const response = await fetch(TOKEN_URL, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-API-VERSION": "1.0",
      Authorization: `Bearer ${key}`,
    },
    body: JSON.stringify({
      key_type: "approval",
      checksum: checksum(secret, ts),
      timestamp: ts,
    }),
  });
  if (!response.ok) throw new Error("token");
  const payload = await response.json();
  const token = payload.token || (payload.payload && payload.payload.token);
  if (!token) throw new Error("token");
  return token;
}

async function growwGet(url, token, params) {
  const target = new URL(url);
  if (params) {
    Object.keys(params).forEach(function (key) {
      target.searchParams.set(key, params[key]);
    });
  }
  const response = await fetch(target, {
    headers: {
      Accept: "application/json",
      "X-API-VERSION": "1.0",
      Authorization: `Bearer ${token}`,
    },
  });
  if (!response.ok) throw new Error("groww");
  return response.json();
}

function cashKeys(row) {
  const nse = String(row.nse_symbol || row.symbol || "")
    .trim()
    .toUpperCase();
  return ["NSE_" + nse, "BSE_" + nse];
}

function asPrice(value) {
  if (value == null || value === "") return null;
  const n = Number(String(value).replace(/,/g, ""));
  return Number.isFinite(n) ? n : null;
}

module.exports = async function (req, res) {
  if (!authorized(req)) {
    res.statusCode = 401;
    res.setHeader("Content-Type", "text/plain; charset=utf-8");
    res.end("auth");
    return;
  }
  const symbols = loadSymbols();
  const empty = {};
  symbols.forEach(function (row) {
    if (!row || !row.symbol) return;
    empty[row.symbol] = {
      qty: "—",
      cost: "—",
      cmp: "—",
      ret: "—",
      up: false,
      down: false,
    };
  });
  try {
    const token = await accessToken();
    const holdingsBody = await growwGet(HOLDINGS_URL, token);
    const holdings = (((holdingsBody.payload || {}).holdings) || []).filter(
      function (row) {
        return row && row.trading_symbol;
      }
    );
    const byGroww = {};
    holdings.forEach(function (row) {
      byGroww[String(row.trading_symbol).trim().toUpperCase()] = row;
    });
    const keys = [];
    const seen = {};
    symbols.forEach(function (row) {
      cashKeys(row).forEach(function (key) {
        if (!seen[key]) {
          seen[key] = true;
          keys.push(key);
        }
      });
    });
    let prices = {};
    if (keys.length) {
      const ltpBody = await growwGet(LTP_URL, token, {
        segment: "CASH",
        exchange_symbols: keys.join(","),
      });
      prices = ltpBody.payload || {};
    }
    const out = {};
    symbols.forEach(function (row) {
      const symbol = row.symbol;
      const nse = String(row.nse_symbol || symbol || "")
        .trim()
        .toUpperCase();
      const held = byGroww[nse] || byGroww[String(symbol).toUpperCase()];
      let last = null;
      cashKeys(row).forEach(function (key) {
        if (last == null) last = asPrice(prices[key]);
      });
      const cost = held ? Number(held.average_price) : null;
      const qty = held ? Number(held.quantity) : null;
      const ret = fmtRet(last, cost);
      out[symbol] = {
        qty: held ? fmtQty(qty) : "—",
        cost: held ? fmtPrice(cost) : "—",
        cmp: fmtPrice(last),
        ret: ret.ret,
        up: ret.up,
        down: ret.down,
      };
    });
    res.statusCode = 200;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.setHeader("Cache-Control", "private, no-store");
    res.end(JSON.stringify(out));
  } catch {
    res.statusCode = 200;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.setHeader("Cache-Control", "private, no-store");
    res.end(JSON.stringify(empty));
  }
};
