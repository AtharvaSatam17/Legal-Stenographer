// lib/auth.js
import { jwtVerify, importJWK } from 'jose';

const REGION = process.env.COGNITO_REGION;
const USER_POOL_ID = process.env.COGNITO_USER_POOL_ID;
const COGNITO_CLIENT_ID = process.env.COGNITO_CLIENT_ID;
const COGNITO_JWK_URL = `https://cognito-idp.${REGION}.amazonaws.com/${USER_POOL_ID}/.well-known/jwks.json`;
const ISSUER = `https://cognito-idp.${REGION}.amazonaws.com/${USER_POOL_ID}`;

let jwks;

async function getJWKS() {
  if (!jwks) {
    const res = await fetch(COGNITO_JWK_URL);
    const keys = await res.json();
    jwks = keys;
  }
  return jwks;
}

export async function getUserFromRequest(req) {
  const token = req.cookies?.id_token;
  console.log('Token from cookies:', token);

  if (!token) return null;

  try {
    const JWKS = await getJWKS();
    console.log('Retrieved JWKS:', JWKS);

    const { payload } = await jwtVerify(token, async (header) => {
      console.log('JWT header:', header);
      const key = JWKS.keys.find((k) => k.kid === header.kid);
      console.log('Found matching key:', key);
      if (!key) throw new Error('No matching key found');
      return await importJWK(key, 'RS256');
    }, {
      issuer: ISSUER,
      audience: COGNITO_CLIENT_ID, // optional, but good to have
    });

    console.log('JWT payload:', payload);
    return payload;
  } catch (err) {
    console.warn('Invalid token:', err);
    return null;
  }
}
