const { createHash } = require("crypto");

function token(secret) {
  return createHash("sha256").update("pa:" + secret).digest("hex");
}

function authorized(req) {
  const secret = process.env.PA_SITE_PASSWORD || "";
  if (!secret) return false;
  const header = req.headers.cookie || "";
  const match = header.match(/(?:^|; )pa_gate=([^;]*)/);
  return Boolean(match && match[1] === token(secret));
}

module.exports = { token, authorized };
